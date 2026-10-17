"""Validate source bundle with a real SDK client and a temporary loopback viewer/worker."""

import asyncio
import hashlib
import json
import os
import signal
import sys
import tempfile
import zipfile
from pathlib import Path

import psutil
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from opensubsurface.adapters.local_sources import LocalSources
from opensubsurface.service import Service
from opensubsurface.viewer_links import STATE


async def check(bundle):
    with tempfile.TemporaryDirectory(prefix="opensubsurface-mcpb-") as temporary:
        root = Path(temporary)
        package, home, folder = root / "package", root / "home", root / "source"
        folder.mkdir()
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(package)
        pillars = [v for j in range(2) for i in range(2) for v in [i * 10, j * 10, 0, i * 10, j * 10, 10]]
        (folder / "test.DATA").write_text(
            "RUNSPEC\nDIMENS\n1 1 1 /\nMETRIC\nGRID\nCOORD\n"
            + " ".join(map(str, pillars))
            + " /\nZCORN\n4*0 4*10 /\nACTNUM\n1 /\nPORO\n0.2 /\nNTG\n0.8 /\nPERMX\n100 /\nPROPS\nSWAT\n0.25 /\nREGIONS\nFIPNUM\n1 /\nEND\n"
        )
        service = Service(home)
        source = LocalSources(service.store).register("Synthetic bundle control", folder)
        record = None
        try:
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(package / "server.py")],
                env=dict(OPENSUBSURFACE_HOME=str(home), GRADIO_ANALYTICS_ENABLED="False"),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    async def call(operation, **request):
                        result = await session.call_tool(operation, arguments=dict(request=request))
                        assert not result.isError, result.content
                        payload = json.loads(result.content[0].text)
                        assert "error" not in payload, payload
                        return payload["result"]

                    capability_resource = await session.read_resource("opensubsurface://capabilities")
                    capabilities = json.loads(capability_resource.contents[0].text)
                    assert capabilities["static_deck"]["demonstrated_cells"] == 20_000_000
                    greeting = await call("start")
                    assert greeting["first_connection"]
                    pid = (await call("project_create", name="Source bundle control", vertical_datum="TEST"))[
                        "id"
                    ]
                    listing = await call("source_scan", source_id=source["id"])
                    entry = listing["entries"][0]
                    job = await call(
                        "eclipse_import",
                        project_id=pid,
                        source_id=source["id"],
                        path=entry["path"],
                        file_revision=entry["file_revision"],
                        crs="LOCAL_METRIC",
                        vertical_datum="TEST",
                        length_unit="m",
                        z_direction="down",
                        assumptions=["Synthetic bundle CPU check only"],
                    )
                    for _ in range(500):
                        state = await call("job_status", job_id=job["job_id"])
                        if state["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
                            break
                        await asyncio.sleep(0.5)
                    assert state["status"] == "succeeded", state
                    obj = await call("artifact_inspect", project_id=pid, ref=state["result"])
                    assert obj["summary"]["active_cells"] == 1 and obj.get("viewer_url")
                    record = service.store.get_state(STATE, {})
                    assert record
                    result = dict(
                        status="PASS",
                        source_archive=str(bundle),
                        archive_sha256=hashlib.sha256(Path(bundle).read_bytes()).hexdigest(),
                        sdk_stdio="PASS",
                        shared_local_viewer_controller="PASS",
                        isolated_eclipse_import="PASS",
                        cells=1,
                        scientific_scope="Synthetic geometry import only, no field estimates",
                        claude_desktop_install="NOT RUN",
                        windows_wsl_gpu="NOT RUN",
                    )
        finally:
            record = service.store.get_state(STATE, {})
            service.close()
            if record:
                process = psutil.Process(record["pid"])
                assert process.create_time() == record["process_created"] and any(
                    Path(arg).resolve() == home.resolve() for arg in process.cmdline() if arg.startswith("/")
                )
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except psutil.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        return result


if __name__ == "__main__":
    result = asyncio.run(check(Path("dist/kanysh-basic-0.2.0-dev1.mcpb").resolve()))
    Path("docs/mcpb-check.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
