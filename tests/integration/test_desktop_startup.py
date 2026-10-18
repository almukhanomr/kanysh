"""Real processes and real MCP protocol checks for concurrent Desktop host launches."""

import asyncio
import json
import multiprocessing
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _create_store(home, folder, barrier, results):
    barrier.wait(timeout=30)
    from opensubsurface.adapters.local_sources import LocalSources
    from opensubsurface.persistence.store import Store

    store = Store(home)
    try:
        source = LocalSources(store).register("Concurrent", folder)
        with store.engine.connect() as connection:
            head = connection.exec_driver_sql("select version_num from alembic_version").scalar_one()
            count = connection.exec_driver_sql(
                "select count(*) from state where id='schema_version'"
            ).scalar_one()
        results.put((head, count, source["id"]))
    finally:
        store.engine.dispose()


def test_four_spawned_stores_migrate_and_register_one_source(tmp_path):
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(4), context.Queue()
    folder = tmp_path / "source"
    folder.mkdir()
    processes = [
        context.Process(target=_create_store, args=(str(tmp_path / "home"), str(folder), barrier, results))
        for _ in range(4)
    ]
    try:
        for process in processes:
            process.start()
        records = [results.get(timeout=60) for _ in processes]
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        assert all(head == "0001" and count == 1 for head, count, _ in records)
        assert len({source for _, _, source in records}) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        results.close()


@asynccontextmanager
async def desktop(home, entry=None, variant="cpu", folder=None):
    env = dict(os.environ, OPENSUBSURFACE_HOME=str(home), KANYSH_OPEN_BROWSER="0", KANYSH_VARIANT=variant)
    if folder:
        env["KANYSH_SOURCE_FOLDER"] = str(folder)
    args = [str(entry)] if entry else ["-m", "opensubsurface.desktop"]
    log = home.parent / f"{home.name}-{uuid.uuid4().hex}-client.log"
    with log.open("w", encoding="utf-8") as errlog:
        async with stdio_client(
            StdioServerParameters(command=sys.executable, args=args, env=env), errlog=errlog
        ) as (read, write):
            async with ClientSession(read, write) as session:
                yield session


def diagnostics(home):
    return {
        path.name: path.read_text(encoding="utf-8", errors="replace")[-12000:]
        for path in home.glob("*")
        if path.suffix in (".json", ".log") and path.is_file()
    }


async def tool(session, name="project_list"):
    response = await session.call_tool(name, arguments={"request": {}})
    assert not response.isError
    return json.loads(response.content[0].text)


async def wait_ready(session, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        response = await tool(session)
        if "result" in response:
            return response
        assert response["error"]["code"] == "STARTING", response
        await asyncio.sleep(0.2)
    pytest.fail(str(response))


@pytest.mark.asyncio
async def test_initialize_and_tools_under_three_seconds_while_service_is_slow(tmp_path):
    entry = tmp_path / "server.py"
    entry.write_text(
        "import time\nfrom opensubsurface.desktop import DesktopRuntime,run\nDesktopRuntime._initialize=lambda self: time.sleep(15)\nrun()\n"
    )
    started = time.monotonic()
    async with desktop(tmp_path / "home", entry) as session:
        await session.initialize()
        tools = await session.list_tools()
        elapsed = time.monotonic() - started
        assert elapsed < 3, f"initialize+tools/list took {elapsed:.3f}s"
        assert {"start", "regional_volumes", "source_scan"} <= {t.name for t in tools.tools}
        response = await tool(session)
        assert response["error"]["code"] == "STARTING"
        assert response["error"]["retry_after_seconds"] == 2
        assert response["error"]["stage"] == "STARTING"


@pytest.mark.asyncio
async def test_background_failure_keeps_stdio_alive_and_reports_logs(tmp_path):
    entry = tmp_path / "server.py"
    entry.write_text(
        "from opensubsurface.desktop import DesktopRuntime,run\ndef broken(self): raise RuntimeError('deliberate startup failure')\nDesktopRuntime._initialize=broken\nrun()\n"
    )
    home = tmp_path / "home"
    async with desktop(home, entry) as session:
        await session.initialize()
        for _ in range(40):
            response = await tool(session)
            if response.get("error", {}).get("code") == "FAILED":
                break
            await asyncio.sleep(0.05)
        assert response["error"]["code"] == "FAILED"
        assert "deliberate startup failure" in response["error"]["message"]
        assert response["error"]["log"] == str(home / "startup.log")
        assert (await session.list_tools()).tools
        assert (await tool(session))["error"]["code"] == "FAILED"


@pytest.mark.asyncio
async def test_two_desktops_share_viewer_and_last_client_cleanup(tmp_path):
    from opensubsurface.desktop_lifecycle import alive

    home, folder = tmp_path / "home", tmp_path / "source"
    folder.mkdir()
    (folder / "PORO.INC").write_text("PORO\n1*0.2 /\n")
    first = desktop(home, folder=folder)
    second = desktop(home, folder=folder)
    async with first as a:
        async with second as b:
            await asyncio.gather(a.initialize(), b.initialize())
            await asyncio.gather(wait_ready(a), wait_ready(b))
            one, two = await tool(a, "source_list"), await tool(b, "source_list")
            assert len(one["result"]) == 1 and one == two
            record = json.loads((home / "viewer-process.json").read_text())
            assert record["managed"] and alive(record)
            if sys.platform == "win32":
                assert record["launch_method"] == "windows-wmi"
            leases = list((home / "desktop-leases").glob("*.json"))
            assert len(leases) == 2
            lines = [json.loads(line) for line in (home / "startup.log").read_text().splitlines()]
            assert not any(line["stage"] == "FAILED" for line in lines)
            assert sum(line["stage"] == "VIEWER_RUNNING" for line in lines) == 1
            assert sum(line["stage"] == "VIEWER_ALREADY_RUNNING" for line in lines) == 1
        assert alive(record), diagnostics(home)
        assert "result" in await tool(a)
    deadline = time.monotonic() + 30
    while alive(record) and time.monotonic() < deadline:
        await asyncio.sleep(0.2)
    assert not alive(record), "Managed viewer remained orphaned after the last client"


@pytest.mark.asyncio
async def test_gpu_variant_without_cuda_starts_on_cpu(tmp_path):
    import torch

    if torch.cuda.is_available():
        pytest.skip("Fallback requires a host without CUDA; CUDA acceptance is separate")
    home = tmp_path / "gpu-home"
    async with desktop(home, variant="gpu") as session:
        await session.initialize()
        await wait_ready(session)
        status = json.loads((home / "startup-status.json").read_text())
        assert status["runtime"]["device"] == "cpu"
        assert status["warnings"] and status["home"] == str(home.resolve())
        assert "result" in await tool(session)


def test_gpu_and_cpu_default_homes_are_separate_and_msix_path_is_real(tmp_path, monkeypatch):
    from opensubsurface.desktop import configured_home

    monkeypatch.delenv("OPENSUBSURFACE_HOME", raising=False)
    monkeypatch.setenv("KANYSH_VARIANT", "cpu")
    cpu = configured_home()
    monkeypatch.setenv("KANYSH_VARIANT", "gpu")
    gpu = configured_home()
    assert cpu != gpu and gpu.name.endswith("-gpu")
    monkeypatch.setenv("KANYSH_TEST_MSIX", str(tmp_path / "Packages/Claude/LocalCache/Local"))
    variable = "%KANYSH_TEST_MSIX%" if os.name == "nt" else "$KANYSH_TEST_MSIX"
    expected = tmp_path / "Packages/Claude/LocalCache/Local/custom-home"
    assert configured_home(variable + "/custom-home") == expected.resolve()


@pytest.mark.parametrize("variant", ["cpu", "gpu"])
def test_variants_have_distinct_identity_locked_torch_and_identical_tool_source(tmp_path, variant):
    import importlib.util
    import tomllib
    import zipfile

    spec = importlib.util.spec_from_file_location(
        "mcpb_builder", Path(__file__).parents[2] / "scripts/build_mcpb.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    target = tmp_path / (variant + ".mcpb")
    builder.build(target, variant)
    with zipfile.ZipFile(target) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        project = tomllib.loads(bundle.read("pyproject.toml").decode())
        lock = tomllib.loads(bundle.read("uv.lock").decode())
        expected = "kanysh-basic-gpu" if variant == "gpu" else "kanysh-basic"
        assert manifest["name"] == expected
        assert manifest["user_config"]["home"]["default"].endswith(expected)
        assert manifest["server"]["mcp_config"]["env"]["KANYSH_VARIANT"] == variant
        index = project["tool"]["uv"]["index"][0]
        assert index["explicit"]
        assert index["url"].endswith("cu126" if variant == "gpu" else "cpu")
        assert any("+cu126" in p["version"] for p in lock["package"] if p["name"] == "torch") == (
            variant == "gpu"
        )
        assert (
            bundle.read("src/opensubsurface/mcp/server.py")
            == (Path(__file__).parents[2] / "src/opensubsurface/mcp/server.py").read_bytes()
        )


def test_explicit_device_policy_never_silently_falls_back():
    from opensubsurface.errors import DomainError
    from opensubsurface.execution.device import select_device

    assert select_device("prefer_gpu", available=False, allow_cpu_fallback=True)[0] == "cpu"
    assert select_device("require_gpu", available=True)[0] == "cuda"
    with pytest.raises(DomainError) as error:
        select_device("require_gpu", available=False, allow_cpu_fallback=True)
    assert error.value.code == "NO_COMPATIBLE_GPU"
    with pytest.raises(DomainError):
        select_device("prefer_gpu", compatible=False, available=True)


@pytest.mark.asyncio
async def test_foreign_port_chooses_another_and_standalone_viewer_survives_desktop(tmp_path):
    import socket

    import psutil

    from opensubsurface.desktop_lifecycle import alive
    from opensubsurface.service import Service
    from opensubsurface.setup import ensure_viewer

    home = tmp_path / "standalone-home"
    service = Service(home)
    record = None
    try:
        with socket.socket() as foreign:
            foreign.bind(("127.0.0.1", 0))
            foreign.listen()
            busy = foreign.getsockname()[1]
            viewer = await asyncio.to_thread(ensure_viewer, service, busy, False)
            assert viewer["status"] == "RUNNING"
            assert f":{busy}/" not in viewer["url"]
            record = json.loads((home / "viewer-process.json").read_text(encoding="utf-8"))
            assert not record["managed"]
            async with desktop(home) as session:
                await session.initialize()
                await wait_ready(session)
                assert (
                    json.loads((home / "startup-status.json").read_text(encoding="utf-8"))["viewer"]["status"]
                    == "ALREADY_RUNNING"
                )
            assert alive(record), "Desktop shutdown must preserve an independently launched viewer"
    finally:
        service.close()
        if record and alive(record):
            process = psutil.Process(record["pid"])
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 15)
            except psutil.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 5)


@pytest.mark.asyncio
async def test_managed_viewer_exits_when_desktop_process_is_killed(tmp_path):
    import psutil

    from opensubsurface.desktop_lifecycle import alive

    home = tmp_path / "abrupt-home"
    async with desktop(home) as session:
        await session.initialize()
        await wait_ready(session)
        status = json.loads((home / "startup-status.json").read_text(encoding="utf-8"))
        record = json.loads((home / "viewer-process.json").read_text(encoding="utf-8"))
        assert record and alive(record)
        # Kill the actual server recorded by itself. Windows venv's Popen PID can
        # belong to a redirector; killing only that wrapper leaves Python alive.
        process = psutil.Process(status["pid"])
        process.kill()
        deadline = time.monotonic() + 30
        while alive(record) and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        # Assert before SDK context cleanup, so the SDK's own job teardown cannot
        # make a missing lease supervisor look successful.
        assert not alive(record), diagnostics(home)


def test_status_atomic_replace_retries_windows_sharing_violation(tmp_path, monkeypatch):
    from opensubsurface.desktop_lifecycle import write_json

    path = tmp_path / "status.json"
    write_json(path, {"stage": "STARTING"})
    replace = os.replace
    attempts = []

    def held_by_reader(source, target):
        attempts.append(True)
        if len(attempts) == 1:
            assert json.loads(path.read_text()) == {"stage": "STARTING"}
            error = PermissionError("sharing violation")
            error.winerror = 32
            raise error
        replace(source, target)

    monkeypatch.setattr(os, "replace", held_by_reader)
    write_json(path, {"stage": "MCP_READY"})
    assert json.loads(path.read_text()) == {"stage": "MCP_READY"}
    assert len(attempts) == 2 and not list(tmp_path.glob("*.tmp"))


def test_status_replace_preserves_previous_record_on_permanent_denial(tmp_path, monkeypatch):
    from opensubsurface.desktop_lifecycle import write_json

    path = tmp_path / "status.json"
    write_json(path, {"stage": "STARTING"})

    def denied(source, target):
        raise PermissionError("permanent denial")

    monkeypatch.setattr(os, "replace", denied)
    with pytest.raises(PermissionError):
        write_json(path, {"stage": "MCP_READY"})
    assert json.loads(path.read_text()) == {"stage": "STARTING"}
    assert not list(tmp_path.glob("*.tmp"))
