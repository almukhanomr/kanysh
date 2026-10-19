"""Validate source bundle with a real SDK client and a temporary loopback viewer/worker."""

import asyncio
import hashlib
import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import psutil
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from opensubsurface.service import Service
from opensubsurface.viewer_links import STATE


async def check(bundle, variant="cpu"):
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
        record = None
        result = {}
        try:
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(package / "server.py")],
                env=dict(
                    OPENSUBSURFACE_HOME=str(home),
                    GRADIO_ANALYTICS_ENABLED="False",
                    KANYSH_OPEN_BROWSER="0",
                    KANYSH_SOURCE_FOLDER=str(folder),
                    PYTHONUTF8="1",
                    KANYSH_VARIANT=variant,
                ),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    started = time.perf_counter()
                    await session.initialize()
                    await session.list_tools()
                    initialize_seconds = time.perf_counter() - started

                    async def call(operation, **request):
                        for _ in range(300):
                            result = await session.call_tool(operation, arguments=dict(request=request))
                            assert not result.isError, result.content
                            payload = json.loads(result.content[0].text)
                            if payload.get("error", {}).get("code") == "STARTING":
                                await asyncio.sleep(0.2)
                                continue
                            assert "error" not in payload, payload
                            return payload["result"]
                        raise TimeoutError("Desktop did not become ready")

                    # start/source_list answer from SERVICE_READY; wait for the full controller first.
                    await call("compute_targets_list")
                    greeting = await call("start")
                    capability_resource = await session.read_resource("opensubsurface://capabilities")
                    capabilities = json.loads(capability_resource.contents[0].text)
                    assert capabilities["static_deck"]["demonstrated_cells"] == 20_000_000
                    assert greeting["first_connection"]
                    startup = json.loads((home / "startup-status.json").read_text(encoding="utf-8"))
                    assert startup["stage"] == "MCP_READY" and (home / "startup.log").is_file()
                    pid = (await call("project_create", name="Source bundle control", vertical_datum="TEST"))[
                        "id"
                    ]
                    sources = await call("source_list")
                    assert len(sources) == 1 and Path(sources[0]["root"]).resolve() == folder.resolve()
                    source = sources[0]
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
                        variant=variant,
                        initialize_and_list_seconds=initialize_seconds,
                        installer_selected_folder="PASS",
                        startup_log="PASS",
                        shared_local_viewer_controller="PASS",
                        isolated_eclipse_import="PASS",
                        cells=1,
                        scientific_scope="Synthetic geometry import only, no field estimates",
                        claude_desktop_install="NOT RUN",
                        windows_native="NOT RUN",
                        windows_claude_uv_install="NOT RUN",
                    )
        finally:
            record = service.store.get_state(STATE, {})
            service.close()
            if record:
                for _ in range(150):
                    try:
                        process = psutil.Process(record["pid"])
                        if (
                            process.create_time() != record["process_created"]
                            or process.status() == psutil.STATUS_ZOMBIE
                        ):
                            break
                    except psutil.NoSuchProcess:
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise AssertionError("Viewer remained alive after last Desktop lease")
                result["last_client_cleanup"] = "PASS"
        return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["cpu", "gpu"], default="cpu")
    args = parser.parse_args()
    suffix = "-gpu" if args.variant == "gpu" else ""
    result = asyncio.run(check(Path(f"dist/kanysh-basic{suffix}-0.2.0-dev5.mcpb").resolve(), args.variant))
    Path(f"docs/mcpb{suffix}-check.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
