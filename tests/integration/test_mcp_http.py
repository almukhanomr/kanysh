import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from opensubsurface.api.app import create_app


@pytest.mark.asyncio
async def test_http_mcp_and_rest_share_service_artifacts_and_authorization(service, monkeypatch):
    monkeypatch.setenv("OPENSUBSURFACE_TOKEN", "local-test-token")
    app = create_app(service=service, with_ui=False)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as anonymous:
            denied = await anonymous.post(
                "/mcp/", json=dict(jsonrpc="2.0", id=1, method="initialize", params={})
            )
            assert denied.status_code == 401
            assert (
                await anonymous.get("/api/v1/projects", headers={"Authorization": "local-test-token"})
            ).status_code == 401
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8765",
            headers={"Authorization": "Bearer local-test-token"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1:8765/mcp/", http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert "simulation_snapshot" in {t.name for t in tools.tools}
                    assert "development_rank" in {t.name for t in tools.tools}
                    created = await session.call_tool(
                        "project_create", arguments={"request": dict(name="HTTP MCP", vertical_datum="TEST")}
                    )
                    project = json.loads(created.content[0].text)["result"]
                    rest = await client.get("/api/v1/projects")
                    assert project["id"] in {p["id"] for p in rest.json()}
                    inspected = await session.call_tool(
                        "project_inspect", arguments={"request": dict(project_id=project["id"])}
                    )
                    payload = json.loads(inspected.content[0].text)["result"]
                    assert payload["project"]["name"] == "HTTP MCP"
