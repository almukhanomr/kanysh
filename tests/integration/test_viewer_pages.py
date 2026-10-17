import base64
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from opensubsurface.api.app import create_app
from opensubsurface.demo_norne import open_demo
from opensubsurface.viewer_links import base_url


@pytest.mark.asyncio
@pytest.mark.parametrize("with_ui", [False, True])
async def test_mcp_report_scene_links_resolve_only_when_viewer_runs(service, tmp_path, with_ui):
    if with_ui:
        pytest.importorskip("gradio")
    pid = service.invoke("project_create", dict(name="<script>fixture</script>", vertical_datum="TEST"))["id"]
    html = tmp_path / "report.html"
    html.write_text("<!doctype html><p>TEST_ONLY stored result</p>")
    png = tmp_path / "volumes.png"
    png.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jFOQAAAAASUVORK5CYII="
        )
    )
    report = service.store.publish(
        pid, "calculation_report", dict(validation_status="PASS"), {"report.html": html, "volumes.png": png}
    )
    scene = service.store.publish(pid, "scene", {}, {"scene.html": html})
    app = create_app(service=service, with_ui=with_ui, mcp_profile="agent")
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
                    for obj in (report, scene):
                        ref = dict(id=obj["id"], revision=obj["revision"])
                        response = await session.call_tool(
                            "artifact_inspect", arguments=dict(request=dict(project_id=pid, ref=ref))
                        )
                        value = json.loads(response.content[0].text)["result"]
                        if with_ui:
                            assert "/viewer/projects/" in value["viewer_url"]
                            page = await http.get(value["viewer_url"])
                            assert (
                                page.status_code == 200
                                and 'sandbox="allow-scripts allow-downloads"' in page.text
                            )
                            filename = "report.html" if obj is report else "scene.html"
                            content = await http.get(value["viewer_url"] + "/content/" + filename)
                            assert content.status_code == 200
                            assert "sandbox allow-scripts" in content.headers["content-security-policy"]
                            assert "allow-same-origin" not in content.headers["content-security-policy"]
                            assert (
                                await http.get(value["viewer_url"] + "/content/other.html")
                            ).status_code == 403
                        else:
                            assert "viewer_url" not in value
                    response = await session.call_tool(
                        "result_preview",
                        arguments=dict(
                            request=dict(
                                project_id=pid, report=dict(id=report["id"], revision=report["revision"])
                            )
                        ),
                    )
                    value = json.loads(response.content[0].text)["result"]
                    assert value["report"] == dict(id=report["id"], revision=report["revision"])
                    assert ("viewer_url" in value) == with_ui
                    assert any(content.type == "image" for content in response.content)
            if with_ui:
                assert "&lt;script&gt;" in (await http.get("/viewer/")).text
    assert base_url(service) is None


def test_norne_button_data_are_bundled_offline_and_idempotent(service, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Viewer demo must not run jobs or use the network")

    monkeypatch.setattr(service, "invoke", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    first = open_demo(service.store)
    second = open_demo(service.store)
    assert first == second
    objects = service.store.list_objects(first["project_id"])
    assert {"scene", "calculation_report", "properties"} <= {o["kind"] for o in objects}
    assert service.store.list_jobs(first["project_id"]) == []
    assert len(service.store.list_projects()) == 1


def test_gradio_ui_has_only_viewer_and_upload_actions(service):
    pytest.importorskip("gradio")
    from opensubsurface.ui.app import create_ui

    ui = create_ui(service)
    assert ui.config["title"] == "Kanysh Basic · Local Viewer"
    types = {component["type"] for component in ui.config["components"]}
    assert not {"chatbot", "audio", "textbox", "code"} & types
    labels = [c.get("props", {}).get("value") for c in ui.config["components"] if c["type"] == "button"]
    assert "Open Norne demo" in labels
    assert all(
        not any(word in str(label) for word in ("Calculate", "Run calculation", "Send")) for label in labels
    )
