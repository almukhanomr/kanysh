"""MCPB entry point: owner configuration, first-run viewer and local startup evidence."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from opensubsurface.platform_io import default_home


def configured_home(value=None):
    value = value or os.environ.get("OPENSUBSURFACE_HOME", "")
    # A portable manifest shows the Windows default; other hosts use their own default.
    if not value or value == r"%LOCALAPPDATA%\kanysh-basic":
        return default_home()
    return Path(os.path.expandvars(os.path.expanduser(value))).absolute()


def run():
    home = configured_home()
    home.mkdir(parents=True, exist_ok=True)

    def status(stage, **details):
        record = dict(stage=stage, time=datetime.now(timezone.utc).isoformat(), **details)
        message = json.dumps(record, ensure_ascii=True)
        print("Kanysh Basic: " + message, file=sys.stderr, flush=True)
        with (home / "startup.log").open("a", encoding="utf-8") as log:
            log.write(message + "\n")
        temporary = home / f"startup-{os.getpid()}.tmp"
        temporary.write_text(message, encoding="utf-8")
        os.replace(temporary, home / "startup-status.json")

    status("STARTING", message="Python dependencies installed by host UV runtime; starting local services")
    service = None
    try:
        from opensubsurface.adapters.local_sources import LocalSources
        from opensubsurface.mcp.server import create_mcp
        from opensubsurface.service import Service
        from opensubsurface.setup import ensure_viewer

        service = Service(home)
        folder = os.environ.get("KANYSH_SOURCE_FOLDER", "")
        if folder and not folder.startswith("${"):
            path = Path(os.path.expandvars(os.path.expanduser(folder)))
            LocalSources(service.store).register(path.name or "Model folder", path)
        first = not (home / "desktop-first-run").exists()
        result = ensure_viewer(
            service, open_browser=first and os.environ.get("KANYSH_OPEN_BROWSER", "1") != "0"
        )
        status("VIEWER_" + result["status"], **result)
        if result["status"] == "FAILED":
            raise RuntimeError("Viewer failed; inspect viewer.log in the results folder")
        (home / "desktop-first-run").touch()
        status(
            "MCP_READY",
            message="Waiting for the chat client; this is not a confirmed client connection",
            viewer_url=result.get("url"),
            dependency_installation="Completed by host before this entry point",
        )
        create_mcp(service, profile="agent").run(transport="stdio")
    except Exception as error:
        status("FAILED", error_type=type(error).__name__, message=str(error))
        raise
    finally:
        if service:
            service.close()


if __name__ == "__main__":
    run()
