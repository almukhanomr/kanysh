import hmac
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from opensubsurface.contracts import CONTRACTS, READ_ONLY
from opensubsurface.errors import DomainError
from opensubsurface.schemas import ProjectCreate
from opensubsurface.service import Service


class Guard:
    def __init__(self, app, token, allowed_origins):
        self.app, self.token, self.allowed_origins = app, token, allowed_origins

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode()
        if origin and origin not in self.allowed_origins:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse(
                {"error": {"code": "ORIGIN_DENIED", "message": "Origin is not allowed"}}, status_code=403
            )(scope, receive, send)
        path = scope["path"]
        authorization = headers.get(b"authorization", b"").decode()
        bearer = authorization[len("Bearer ") :] if authorization.startswith("Bearer ") else ""
        auth = scope.get("session", {}).get("owner") or (
            bool(bearer) and self.token and hmac.compare_digest(bearer, self.token)
        )
        if self.token and not auth and path not in ("/login", "/health"):
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            if path.startswith(("/app", "/viewer")) or path == "/":
                return await RedirectResponse("/login", status_code=303)(scope, receive, send)
            return await JSONResponse(
                {"error": {"code": "AUTH_REQUIRED", "message": "Authentication required"}}, status_code=401
            )(scope, receive, send)
        return await self.app(scope, receive, send)


def create_app(root=None, service=None, with_ui=False, with_mcp=True, mcp_profile="full"):
    service = service or Service(root)

    mcp_server = None
    mcp_app = None
    if with_mcp:
        from opensubsurface.mcp.server import create_mcp

        mcp_server = create_mcp(service, streamable_http_path="/", stateless_http=True, profile=mcp_profile)
        mcp_app = mcp_server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        viewer_record = None
        try:
            service.start()
            if with_ui:
                from opensubsurface.viewer_links import register

                viewer_record = register(
                    service, f"http://127.0.0.1:{int(os.environ.get('OPENSUBSURFACE_PORT', '8765'))}"
                )
            if mcp_server:
                async with mcp_server.session_manager.run():
                    yield
            else:
                yield
        finally:
            if viewer_record:
                from opensubsurface.viewer_links import unregister

                unregister(service, viewer_record)
            service.close()

    app = FastAPI(title="Kanysh Basic", version="0.2.0.dev2", lifespan=lifespan)
    app.state.service = service
    if mcp_app:
        app.mount("/mcp", mcp_app)
        app.state.mcp = mcp_server
    token = os.environ.get("OPENSUBSURFACE_TOKEN", "")
    port = int(os.environ.get("OPENSUBSURFACE_PORT", "8765"))
    allowed = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost", "[::1]")}
    app.add_middleware(Guard, token=token, allowed_origins=allowed)
    app.add_middleware(
        SessionMiddleware, secret_key=secrets.token_hex(32), same_site="strict", https_only=False
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        status = {
            "NOT_FOUND": 404,
            "AUTH_REQUIRED": 401,
            "PERMISSION_DENIED": 403,
            "INPUT_REVISION_CONFLICT": 409,
            "IDEMPOTENCY_CONFLICT": 409,
        }.get(error.code, 422)
        return JSONResponse({"error": error.as_dict()}, status_code=status)

    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_ARGUMENTS",
                    "message": "Arguments do not match the schema",
                    "fields": [str(x["loc"]) for x in error.errors()],
                }
            },
            status_code=422,
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "profile": "local", "version": "0.2.0.dev2"}

    @app.get("/")
    def index():
        return RedirectResponse("/app/" if with_ui else "/docs")

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        return """<!doctype html><html lang="en"><meta charset="utf-8"><title>Kanysh Basic</title>
        <style>body{font:16px system-ui;max-width:400px;margin:100px auto;color:#15354c}input,button{padding:12px;width:100%;box-sizing:border-box;margin:8px 0}</style>
        <h1>Kanysh Basic</h1><p>Local installation key</p><form method="post"><input type="password" name="token" autocomplete="current-password" required><button>Sign in</button></form>"""

    @app.post("/login")
    async def login(request: Request):
        data = await request.form()
        if not token or hmac.compare_digest(str(data.get("token", "")), token):
            request.session["owner"] = True
            return RedirectResponse("/app/" if with_ui else "/docs", status_code=303)
        return JSONResponse({"error": {"code": "AUTH_REQUIRED", "message": "Invalid key"}}, status_code=401)

    @app.get("/api/v1/projects")
    def projects():
        return service.store.list_projects()

    @app.post("/api/v1/projects")
    def project_create(body: ProjectCreate):
        return service.invoke("project_create", body.model_dump())

    @app.get("/api/v1/projects/{project_id}")
    def project_inspect(project_id: str):
        return service.invoke("project_inspect", {"project_id": project_id})

    @app.post("/api/v1/projects/{project_id}/uploads")
    def upload(project_id: str, file: UploadFile = File(...)):
        return service.store.upload(project_id, file.filename, file.file)

    @app.get("/api/v1/projects/{project_id}/artifacts")
    def artifacts(project_id: str, limit: int = 100, offset: int = 0):
        return service.store.list_objects(project_id, max(1, min(limit, 200)), max(0, offset))

    @app.get("/api/v1/projects/{project_id}/artifacts/{object_id}/{revision}")
    def artifact(project_id: str, object_id: str, revision: int):
        return service.store.object(project_id, dict(id=object_id, revision=revision))

    @app.get("/api/v1/projects/{project_id}/artifacts/{object_id}/{revision}/files/{name}")
    def download(project_id: str, object_id: str, revision: int, name: str):
        obj = service.store.object(project_id, dict(id=object_id, revision=revision))
        return FileResponse(service.store.path(obj, name), filename=name)

    @app.get("/api/v1/jobs")
    def jobs(project_id: str | None = None):
        return service.store.list_jobs(project_id)

    @app.get("/api/v1/projects/{project_id}/scenes/{object_id}/{revision}")
    def scene_view(project_id: str, object_id: str, revision: int):
        obj = service.store.object(project_id, dict(id=object_id, revision=revision))
        if obj["kind"] != "scene":
            raise DomainError("TYPE_MISMATCH", "Expected scene artifact")
        if not with_ui:
            raise DomainError("VIEWER_UNAVAILABLE", "Start serve --ui to view scenes")
        from opensubsurface.viewer_links import artifact_path

        return RedirectResponse(artifact_path(project_id, obj), status_code=303)

    @app.get("/api/v1/jobs/{job_id}")
    def job(job_id: str):
        return service.store.job(job_id)

    @app.get("/api/v1/jobs/{job_id}/logs")
    def job_logs(job_id: str):
        return service.invoke("job_logs", dict(job_id=job_id))

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return service.cancel(job_id)

    @app.get("/api/v1/targets")
    def targets():
        return service.invoke("compute_targets_list", {})

    @app.get("/api/v1/projects/{project_id}/export")
    def export(project_id: str):
        directory = service.store.root / "exports"
        directory.mkdir(exist_ok=True)
        path = directory / (project_id + ".zip")
        service.store.export_project(project_id, path)
        return FileResponse(path, filename="kanysh-basic-" + project_id + ".zip")

    @app.post("/api/v1/projects/import")
    def project_import(file: UploadFile = File(...)):
        import tempfile

        with tempfile.NamedTemporaryFile(dir=service.store.root) as temp:
            total = 0
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > 256 * 1024**2:
                    raise DomainError("UPLOAD_TOO_LARGE", "ZIP exceeds the 256 MB limit")
                temp.write(chunk)
            temp.flush()
            return service.store.import_project(temp.name)

    for name, schema in CONTRACTS.items():

        def make_route(operation, input_schema):
            def endpoint(body):
                result = service.invoke(operation, body.model_dump(mode="json"))
                return JSONResponse(
                    result, status_code=202 if isinstance(result, dict) and "job_id" in result else 200
                )

            endpoint.__name__ = operation
            endpoint.__annotations__ = {"body": input_schema}
            return endpoint

        app.add_api_route(
            "/api/v1/operations/" + name,
            make_route(name, schema),
            methods=["POST"],
            tags=["read" if name in READ_ONLY else "commands"],
            name=name,
        )

    if with_ui:
        try:
            import gradio as gr
        except ImportError as error:
            raise DomainError("UI_NOT_INSTALLED", "Install kanysh-basic[ui] to run --ui") from error

        from opensubsurface.ui.app import create_ui
        from opensubsurface.ui.pages import mount_pages

        mount_pages(app, service)
        app = gr.mount_gradio_app(
            app,
            create_ui(service),
            path="/app",
            show_error=False,
            allowed_paths=[],
            blocked_paths=[str(service.store.root / "metadata.db")],
        )
    return app
