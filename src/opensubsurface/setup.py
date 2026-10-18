"""Owner-invoked workstation setup. Never called by an MCP tool."""

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import portalocker

from opensubsurface.errors import require


def register_config(path, server):
    path = Path(path)
    require(not path.is_symlink(), "CONFIG_UNSAFE", "Configuration cannot be a symlink")
    before = path.read_bytes() if path.exists() else None
    config = json.loads(before) if before is not None else {}
    require(isinstance(config, dict), "CONFIG_INVALID", "Expected JSON object; original file preserved")
    existing = config.setdefault("mcpServers", {})
    require(isinstance(existing, dict), "CONFIG_INVALID", "mcpServers must be an object")
    current = existing.get("kanysh-basic")
    require(
        current in (None, server),
        "CONFIG_CONFLICT",
        "Existing kanysh-basic registration differs; original preserved. Remove or rename it explicitly.",
    )
    if current == server:
        return dict(path=str(path), status="UNCHANGED", backup=None)
    existing["kanysh-basic"] = server
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if before is not None:
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(path.name + "." + suffix + ".bak")
        with backup.open("xb") as stream:
            stream.write(before)
        shutil.copymode(path, backup)
    temp = path.with_name(path.name + ".kanysh-basic.tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temp, 0o600)
        require(
            (path.read_bytes() if path.exists() else None) == before,
            "CONFIG_CHANGED",
            "Configuration changed during setup; original preserved",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return dict(path=str(path), status="CONFIGURED", backup=str(backup) if backup else None)


def config_paths(user_home=None, platform=None):
    root = Path(user_home or Path.home())
    platform = platform or sys.platform
    desktop = None
    if platform == "linux" and os.environ.get("WSL_INTEROP") and user_home is None:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "[Environment]::GetFolderPath('ApplicationData')"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        converted = subprocess.run(
            ["wslpath", "-u", result.stdout.strip()], capture_output=True, text=True, timeout=10, check=True
        )
        desktop = Path(converted.stdout.strip()) / "Claude/claude_desktop_config.json"
    if platform == "darwin":
        desktop = root / "Library/Application Support/Claude/claude_desktop_config.json"
    elif platform == "win32":
        desktop = (
            Path(os.environ.get("APPDATA", root / "AppData/Roaming")) / "Claude/claude_desktop_config.json"
        )
    return desktop, root / ".claude.json"


def ensure_viewer(service, port=8765, open_browser=True, managed=False, first_run=False):
    # One spawn/check sequence per home, independent of the control-plane lock.
    with portalocker.Lock(service.store.root / "viewer-start.lock", mode="a", timeout=120):
        marker = service.store.root / "desktop-first-run"
        show = open_browser and (not first_run or not marker.exists())
        result = _ensure_viewer(service, port, show, managed)
        if first_run and result["status"] in ("RUNNING", "ALREADY_RUNNING"):
            marker.touch(exist_ok=True)
        return result


def _ensure_viewer(service, port, open_browser, managed):
    import httpx

    from opensubsurface.desktop_lifecycle import alive, identity, write_json
    from opensubsurface.viewer_links import base_url

    process_record = service.store.root / "viewer-process.json"
    if process_record.exists():
        record = json.loads(process_record.read_text(encoding="utf-8"))
        if record.get("stopping"):
            deadline = time.monotonic() + 30
            while alive(record) and time.monotonic() < deadline:
                time.sleep(0.1)
            require(not alive(record), "VIEWER_STOPPING", "Previous viewer is stopping; retry shortly")
    origin = base_url(service)
    if origin:
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                health = client.get(origin + "/health").json()
            if health.get("status") != "ok" or health.get("home") not in (
                None,
                str(service.store.root.resolve()),
            ):
                origin = None
        except (httpx.HTTPError, ValueError):
            origin = None
    if origin:
        if open_browser:
            webbrowser.open(origin + "/app/")
        return dict(status="ALREADY_RUNNING", url=origin + "/app/")
    require(
        importlib.util.find_spec("gradio") is not None,
        "UI_NOT_INSTALLED",
        "Install kanysh-basic[ui] before starting viewer",
    )
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log = service.store.root / "viewer.log"
    from opensubsurface.execution.runner import process_options

    kwargs = process_options()
    if managed and sys.platform == "win32":
        from opensubsurface.desktop_spawn import launch_windows_viewer

        process = launch_windows_viewer(service.store.root, port, log)
    else:
        process = _spawn_viewer(service, port, log, managed, kwargs)
    write_json(
        process_record,
        dict(
            identity(process.pid),
            managed=managed,
            stopping=False,
            launch_method=getattr(process, "launch_method", "subprocess"),
        ),
    )
    for _ in range(300):
        if process.poll() is not None:
            return dict(status="FAILED", log=str(log), returncode=process.returncode)
        try:
            with httpx.Client(trust_env=False, timeout=1) as client:
                response = client.get(url + "/health")
                if (
                    response.is_success
                    and response.json().get("status") == "ok"
                    and response.json().get("home") == str(service.store.root.resolve())
                ):
                    if open_browser:
                        webbrowser.open(url + "/app/")
                    return dict(status="RUNNING", pid=process.pid, url=url + "/app/", log=str(log))
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.2)
    return dict(
        status="FAILED", pid=process.pid, url=url + "/app/", log=str(log), reason="Viewer startup timed out"
    )


def _spawn_viewer(service, port, log, managed, kwargs):
    with log.open("ab") as stream:
        process = subprocess.Popen(
            [sys.executable, "-m", "opensubsurface.desktop_viewer", str(service.store.root), str(port)]
            if managed
            else [
                sys.executable,
                "-m",
                "opensubsurface.cli",
                "--home",
                str(service.store.root.resolve()),
                "serve",
                "--ui",
                "--mcp-profile",
                "agent",
                "--port",
                str(port),
            ],
            stdout=stream,
            stderr=stream,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
    return process


def setup(service, desktop_path=None, code_path=None, start_viewer=True, open_browser=True):
    desktop, code = config_paths()
    desktop = Path(desktop_path) if desktop_path else desktop
    code = Path(code_path) if code_path else code
    args = [
        "-m",
        "opensubsurface.cli",
        "--home",
        str(service.store.root.resolve()),
        "mcp",
        "--profile",
        "agent",
    ]
    server = dict(command=sys.executable, args=args)
    desktop_server = server
    if os.environ.get("WSL_INTEROP"):
        distribution = os.environ.get("WSL_DISTRO_NAME")
        require(bool(distribution), "SETUP_ENVIRONMENT", "WSL_DISTRO_NAME required for desktop launcher")
        desktop_server = dict(
            command="wsl.exe", args=["--distribution", distribution, "--exec", sys.executable, *args]
        )
    desktop_result = (
        register_config(desktop, desktop_server)
        if desktop
        else dict(status="NOT RUN", reason="Claude Desktop native configuration unsupported on this OS")
    )
    code_result = register_config(code, dict(type="stdio", **server))
    result = dict(
        home=str(service.store.root.resolve()),
        python=sys.version.split()[0],
        environment={
            name: "AVAILABLE" if importlib.util.find_spec(name) else "MISSING"
            for name in ("numpy", "xtgeo", "gradio", "pyvista", "openpyxl", "reportlab")
        },
        claude_desktop=desktop_result,
        claude_code=code_result,
        client_connection_validation="NOT RUN",
        windows_gpu_acceptance="NOT RUN",
        instruction="Restart Claude clients. Invoke begin/start, then add a folder in the viewer and call folder_assess. Configuration is not proof of a successful client connection.",
    )
    result["viewer"] = (
        ensure_viewer(service, open_browser=open_browser)
        if start_viewer
        else dict(status="NOT RUN", reason="disabled by owner option")
    )
    return result
