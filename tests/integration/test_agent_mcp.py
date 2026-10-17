import asyncio
import base64
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from opensubsurface.adapters.local_sources import LocalSources
from opensubsurface.api.app import create_app


@pytest.mark.asyncio
async def test_agent_profile_full_gempy_source_plan_validate_report_and_image(service, tmp_path):
    folder = tmp_path / "geological-inputs"
    folder.mkdir()
    (folder / "surfaces.csv").write_text(
        "horizon,x,y,z\nH,0,0,-1020\nH,1000,0,-1020\nH,0,1000,-1020\nH,1000,1000,-1020\n"
    )
    (folder / "orientations.csv").write_text("horizon,x,y,z,nx,ny,nz\nH,500,500,-1020,0,0,1\n")
    source = LocalSources(service.store).register("Synthetic GemPy fixture", folder)
    app = create_app(service=service, with_ui=False, mcp_profile="agent")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as http:
            async with streamable_http_client("http://127.0.0.1:8765/mcp/", http_client=http) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = {t.name for t in (await session.list_tools()).tools}
                    assert (
                        len(tools) >= 24
                        and "eclipse_import" in tools
                        and "grid_import" in tools
                        and {"scene_show", "scene_export", "scene_inspect", "seismic_source_import"} <= tools
                        and "calculation_plan" in tools
                        and "cloud_launch" not in tools
                    )
                    guide = await session.read_resource("opensubsurface://guide")
                    assert "NEEDS_INPUT" in guide.contents[0].text
                    assert "static_calculation" in {p.name for p in (await session.list_prompts()).prompts}

                    async def call(operation, **request):
                        response = await session.call_tool(operation, arguments=dict(request=request))
                        assert not response.isError, response.content
                        data = json.loads(response.content[0].text)
                        assert "error" not in data, data
                        return data["result"]

                    pid = (await call("project_create", name="MCP end-to-end", vertical_datum="TEST"))["id"]
                    assert (await call("calculation_plan", project_id=pid))["status"] == "NEEDS_INPUT"
                    inventory = await call("source_scan", source_id=source["id"])
                    inputs = []
                    for entry in inventory["entries"]:
                        metadata = await call(
                            "source_inspect",
                            source_id=source["id"],
                            path=entry["path"],
                            file_revision=entry["file_revision"],
                        )
                        role = "orientations" if "nx" in metadata["columns"] else "surfaces"
                        assert role in metadata["candidate_kinds"]
                        inputs.append(
                            dict(
                                kind=role,
                                source_id=source["id"],
                                path=entry["path"],
                                file_revision=entry["file_revision"],
                                units=dict(x="m", y="m", z="m"),
                            )
                        )
                    plan = await call(
                        "calculation_plan",
                        project_id=pid,
                        name="Synthetic evidence <script>window.injected=1</script>",
                        method="gempy",
                        horizontal_assumption=False,
                        inputs=inputs,
                        grid=dict(shape=[3, 4, 8], extent=[0, 1000, 0, 1000, -1040, -1000]),
                        zones={
                            "1": dict(phi=0, ntg=0, sw=1, permeability_md=0),
                            "2": dict(phi=0.2, ntg=0.8, sw=0.25, permeability_md=100),
                        },
                        zone_ids=[2],
                        bo=1.2,
                        contacts=[
                            dict(name="full", z_m=-1040),
                            dict(name="half", z_m=-1030),
                            dict(name="dry", z_m=-1020),
                        ],
                        assumptions=[
                            "Synthetic horizontal horizon; upper zone excluded; no field-data claim"
                        ],
                        uncertainty=dict(
                            contact_name="full",
                            distributions=dict(phi=dict(kind="uniform", low=0.15, high=0.25)),
                            count=4,
                            seed=42,
                        ),
                    )
                    plan_ref = dict(id=plan["id"], revision=plan["revision"])
                    assert (await call("plan_validate", project_id=pid, plan=plan_ref))["status"] == "VALID"
                    submitted = await call("calculation_run", project_id=pid, plan=plan_ref)
            # Reconnect a new MCP session while the persistent service continues computation.
            async with streamable_http_client("http://127.0.0.1:8765/mcp/", http_client=http) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    for _ in range(240):
                        result = await session.call_tool(
                            "calculation_status",
                            arguments=dict(request=dict(project_id=pid, run_id=submitted["run_id"])),
                        )
                        status = json.loads(result.content[0].text)["result"]
                        if status["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
                            break
                        await asyncio.sleep(0.5)
                    assert status["status"] == "succeeded", status
                    report = service.store.object(pid, status["report"])
                    data = json.loads(service.store.path(report, "report.json").read_text())
                    assert data["validation_status"] == "PASS"
                    assert [row["STOIIP"] for row in data["contacts"]] == pytest.approx([2e6, 1e6, 0])
                    html = service.store.path(report, "report.html").read_text()
                    assert "<script>" not in html and "&lt;script&gt;" in html
                    image = await session.call_tool(
                        "result_preview",
                        arguments=dict(request=dict(project_id=pid, report=status["report"])),
                    )
                    assert any(
                        item.type == "image" and item.mimeType == "image/png" for item in image.content
                    )
                    metadata = json.loads(image.content[0].text)["result"]
                    resource = await session.read_resource(metadata["resource_uri"])
                    assert base64.b64decode(resource.contents[0].blob).startswith(b"\x89PNG")
