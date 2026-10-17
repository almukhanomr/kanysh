import asyncio
import ipaddress
import json
import os
import socket
import subprocess
import sys

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from opensubsurface.errors import DomainError
from opensubsurface.service import Service


@pytest.mark.parametrize("attempt_executor", [False, True])
def test_metadata_client_and_failed_second_executor_do_not_cancel_owner_jobs(service, attempt_executor):
    service.start()
    pid = service.invoke("project_create", dict(name="Owner", vertical_datum="TEST"))["id"]
    job, _ = service.store.put_job("model_build", dict(project_id=pid, horizontal_assumption=True))
    reader = Service(service.store.root)
    try:
        if attempt_executor:
            with pytest.raises(DomainError) as error:
                reader.start()
            assert error.value.code == "CONTROL_PLANE_ACTIVE"
        else:
            assert reader.invoke("source_list", {}) == []
    finally:
        reader.close()
    assert service.store.job(job["id"])["status"] == "queued"
    assert service.owns_controller and reader.file_lock is None


def test_headless_api_does_not_import_gradio(tmp_path):
    script = """
import sys
from opensubsurface.api.app import create_app
app = create_app(root=sys.argv[1], with_ui=False)
assert 'gradio' not in sys.modules
app.state.service.close()
"""
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "headless")], check=True, capture_output=True
    )


def test_local_scheduler_diagnostics_bind_only_loopback(service):
    service.start()
    nodes = [service.cluster.scheduler, *service.cluster.workers.values()]
    for node in nodes:
        sockets = node.http_server._sockets.values()
        assert sockets
        assert all(ipaddress.ip_address(sock.getsockname()[0]).is_loopback for sock in sockets)


@pytest.mark.asyncio
async def test_persistent_local_cli_headless_mcp_sources_and_import(tmp_path):
    home = tmp_path / "home"
    folder = tmp_path / "well-data"
    folder.mkdir()
    (folder / "collars.csv").write_text("well_id,x,y,reference_elevation\nW1,0,0,0\n")
    base = [sys.executable, "-m", "opensubsurface.cli", "--home", str(home)]
    registered = subprocess.run(
        [*base, "source-add", "Wells", str(folder)], check=True, capture_output=True, text=True
    )
    source = json.loads(registered.stdout)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = dict(os.environ, OPENSUBSURFACE_TOKEN="headless-test-only")
    log = (tmp_path / "headless.log").open("w")
    process = subprocess.Popen(
        [*base, "serve", "--no-ui", "--port", str(port)], env=env, stdout=log, stderr=log
    )
    try:
        async with httpx.AsyncClient(
            base_url=url, timeout=30, headers={"Authorization": "Bearer headless-test-only"}
        ) as http:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError((tmp_path / "headless.log").read_text())
                try:
                    if (await http.get("/health")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            assert (await http.get("/app/")).status_code == 404
            assert (await http.get("/", follow_redirects=False)).headers["location"] == "/docs"
            async with streamable_http_client(url + "/mcp/", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = {tool.name for tool in (await session.list_tools()).tools}
                    assert {"source_list", "source_scan", "source_upload"} <= tools
                    assert not {"source_add", "source_remove", "source_register"} & tools

                    async def call(operation, **request):
                        response = await session.call_tool(operation, arguments=dict(request=request))
                        payload = json.loads(response.content[0].text)
                        assert "error" not in payload, payload
                        return payload["result"]

                    sources = await call("source_list")
                    assert sources[0]["id"] == source["id"]
                    pid = (await call("project_create", name="Workstation", vertical_datum="TEST"))["id"]
                    listing = await call("source_scan", source_id=source["id"])
                    entry = listing["entries"][0]
                    uploaded = await call(
                        "source_upload",
                        project_id=pid,
                        source_id=source["id"],
                        path=entry["path"],
                        file_revision=entry["file_revision"],
                    )
                    submitted = await call(
                        "dataset_import",
                        project_id=pid,
                        upload_id=uploaded["id"],
                        kind="collars",
                        units={"x": "m", "y": "m", "reference_elevation": "m"},
                        crs="LOCAL_METRIC",
                        vertical_datum="TEST",
                    )
            # The MCP conversation has disconnected; the HTTP daemon still owns the job.
            for _ in range(200):
                job = (await http.get("/api/v1/jobs/" + submitted["job_id"])).json()
                if job["status"] in ("succeeded", "failed", "interrupted", "cancelled"):
                    break
                await asyncio.sleep(0.1)
            assert job["status"] == "succeeded", job
            result = (await http.get(f"/api/v1/projects/{pid}/artifacts/{job['result']['id']}/1")).json()
            assert result["kind"] == "dataset" and result["summary"]["rows"] == 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
