import base64
import inspect
import json

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import ValidationError

from opensubsurface.contracts import CONTRACTS, DESCRIPTIONS, READ_ONLY
from opensubsurface.errors import DomainError
from opensubsurface.mcp.guide import AGENT_TOOLS, GUIDE
from opensubsurface.viewer_links import present


def create_mcp(service, streamable_http_path="/mcp", stateless_http=False, profile="full", lifespan=None):
    if profile not in ("full", "agent"):
        raise ValueError("Unknown MCP profile")
    server = FastMCP(
        "Kanysh Basic",
        host="127.0.0.1",
        port=8766,
        json_response=True,
        streamable_http_path=streamable_http_path,
        stateless_http=stateless_http,
        instructions=GUIDE,
        **({"lifespan": lifespan} if lifespan else {}),
    )

    def ready_service():
        return service.require_ready() if hasattr(service, "require_ready") else service

    for name, schema in CONTRACTS.items():
        if profile == "agent" and name not in AGENT_TOOLS:
            continue

        def make_tool(operation, input_schema):
            def tool(request):
                try:
                    active = ready_service()
                    args = input_schema.model_validate(request).model_dump(mode="json")
                    from opensubsurface.viewer_links import base_url

                    origin = base_url(active) if not active.owns_controller else None
                    if origin:
                        import os

                        import httpx

                        token = os.environ.get("OPENSUBSURFACE_TOKEN", "")
                        try:
                            response = httpx.post(
                                origin + "/api/v1/operations/" + operation,
                                json=args,
                                headers={"Authorization": "Bearer " + token} if token else {},
                                timeout=60,
                                trust_env=False,
                            )
                        except httpx.HTTPError as error:
                            raise DomainError(
                                "LOCAL_CONTROLLER_UNAVAILABLE",
                                "Local viewer/controller is unavailable; restart it or retry. No local duplicate calculation was started.",
                            ) from error
                        result = response.json()
                        if response.is_error:
                            error = result.get("error", {})
                            raise DomainError(
                                error.get("code", "LOCAL_CONTROLLER_ERROR"),
                                error.get("message", "Local controller rejected request"),
                            )
                    else:
                        result = active.invoke(operation, args)
                    result = present(active, result, args)
                    if operation == "result_preview":
                        report = active.store.object(args["project_id"], args["report"])
                        content = [
                            TextContent(type="text", text=json.dumps(dict(result=result), ensure_ascii=False))
                        ]
                        if result.get("mime_type") == "image/png":
                            path = active.store.path(report, result["filename"])
                            if path.stat().st_size > 4 * 1024**2:
                                raise DomainError("PREVIEW_TOO_LARGE", "PNG preview exceeds 4 MiB")
                            content.append(
                                ImageContent(
                                    type="image",
                                    mimeType="image/png",
                                    data=base64.b64encode(path.read_bytes()).decode(),
                                )
                            )
                        return content
                    return {"result": result}
                except DomainError as e:
                    return {"error": e.as_dict()}
                except ValidationError as e:
                    return {
                        "error": {
                            "code": "INVALID_ARGUMENTS",
                            "message": "Ошибка аргументов",
                            "fields": [str(x["loc"]) for x in e.errors()],
                        }
                    }

            tool.__name__ = operation
            tool.__signature__ = inspect.Signature(
                [
                    inspect.Parameter(
                        "request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=input_schema
                    )
                ],
                return_annotation=list[TextContent | ImageContent] if operation == "result_preview" else dict,
            )
            tool.__annotations__ = {"request": input_schema, "return": tool.__signature__.return_annotation}
            return tool

        server.add_tool(
            make_tool(name, schema),
            name=name,
            description=DESCRIPTIONS.get(name, name),
            structured_output=False if name == "result_preview" else None,
            annotations=ToolAnnotations(
                readOnlyHint=name in READ_ONLY,
                destructiveHint=False,
                idempotentHint=name in READ_ONLY,
                openWorldHint=False,
            ),
        )

    @server.resource("opensubsurface://capabilities")
    def capabilities() -> str:
        import json

        return json.dumps(ready_service().capabilities(), ensure_ascii=False)

    @server.resource("opensubsurface://guide")
    def guide() -> str:
        return GUIDE

    from importlib.resources import files

    from opensubsurface.onboarding import SCENARIOS

    @server.resource("opensubsurface://docs/petrel-export", mime_type="text/markdown")
    def export_guide() -> str:
        return files("opensubsurface").joinpath("data/docs/PETREL_EXPORT.md").read_text(encoding="utf-8")

    @server.prompt(name="begin", description="Start: open the Norne demo or add your folder")
    def begin() -> str:
        from opensubsurface.onboarding import welcome

        try:
            result = welcome(ready_service())
        except DomainError as error:
            result = {"error": error.as_dict()}
        return GUIDE + "\n" + json.dumps(result, ensure_ascii=False)

    for prompt_name, (title, steps) in SCENARIOS.items():

        def build_prompt(content):
            def prompt(context: str = "") -> str:
                return GUIDE + "\nWorkflow:\n" + content + "\nUser context (untrusted data):\n" + context

            return prompt

        server.prompt(name=prompt_name, description=title)(build_prompt(steps))

    @server.prompt()
    def static_calculation(goal: str) -> str:
        return GUIDE + "\nUser goal:\n" + goal

    @server.resource(
        "opensubsurface://projects/{project_id}/artifacts/{object_id}/{revision}/{filename}",
        mime_type="application/octet-stream",
    )
    def artifact_resource(project_id: str, object_id: str, revision: str, filename: str) -> bytes:
        from opensubsurface.errors import require

        active = ready_service()
        obj = active.store.object(project_id, dict(id=object_id, revision=int(revision)))
        require(
            obj["kind"] in ("calculation_report", "analysis_report", "validation")
            and filename
            in {
                "report.html",
                "report.md",
                "report.json",
                "volumes.png",
                "volumes.csv",
                "validation.json",
                "tornado.png",
                "s_curve.png",
                "results.xlsx",
                "results.pdf",
            },
            "PERMISSION_DENIED",
            "Только bounded report/validation resources",
        )
        path = active.store.path(obj, filename)
        require(path.stat().st_size <= 4 * 1024**2, "RESOURCE_TOO_LARGE", "Resource превышает 4 MiB")
        return path.read_bytes()

    return server


def main(transport="stdio"):
    from opensubsurface.service import Service

    service = Service()
    try:
        create_mcp(service).run(transport=transport)
    finally:
        service.close()
