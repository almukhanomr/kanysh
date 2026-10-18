"""Fast stdio transport with background workstation initialization and shared viewer leases."""

import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from opensubsurface.errors import DomainError
from opensubsurface.platform_io import default_home


def configured_home(value=None):
    variant = os.environ.get("KANYSH_VARIANT", "cpu")
    value = value or os.environ.get("OPENSUBSURFACE_HOME", "")
    defaults = (r"%LOCALAPPDATA%\kanysh-basic", r"%LOCALAPPDATA%\kanysh-basic-gpu")
    if not value or value in defaults:
        base = default_home()
        return base.with_name(base.name + "-gpu") if variant == "gpu" else base
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


class StartupError(DomainError):
    def __init__(self, code, message, stage, home):
        super().__init__(code, message)
        self.stage, self.home = stage, home

    def as_dict(self):
        return dict(
            super().as_dict(),
            stage=self.stage,
            retry_after_seconds=2 if self.code == "STARTING" else None,
            log=str(self.home / "startup.log"),
            home=str(self.home),
        )


class DesktopRuntime:
    def __init__(self, home, initialize=None):
        self.home = Path(home).resolve()
        self.stage = "STARTING"
        self.error = None
        self.service = None
        self.lease = None
        self.details = {}
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.lock = threading.RLock()
        self.initialize = initialize or self._initialize
        self.thread = threading.Thread(target=self._background, daemon=True, name="kanysh-startup")

    def status(self, stage, **details):
        from opensubsurface.desktop_lifecycle import write_json

        with self.lock:
            self.stage = stage
            self.details.update(details)
            record = dict(
                self.details,
                stage=stage,
                time=datetime.now(timezone.utc).isoformat(),
                pid=os.getpid(),
                home=str(self.home),
                variant=os.environ.get("KANYSH_VARIANT", "cpu"),
            )
            message = json.dumps(record, ensure_ascii=True)
            print("Kanysh Basic: " + message, file=sys.stderr, flush=True)
            try:
                self.home.mkdir(parents=True, exist_ok=True)
                with (self.home / "startup.log").open("a", encoding="utf-8") as log:
                    log.write(message + "\n")
                write_json(self.home / "startup-status.json", record)
                write_json(self.home / f"startup-{os.getpid()}.json", record)
            except OSError as error:
                print("Kanysh startup log unavailable: " + str(error), file=sys.stderr, flush=True)

    def start(self):
        self.thread.start()

    def _background(self):
        self.status("STARTING", message="MCP transport is available; initializing local services")
        try:
            self.initialize()
            if not self.stopping.is_set():
                self.status("MCP_READY", message="Local services ready; MCP transport remains available")
                self.ready.set()
        except Exception as error:
            with self.lock:
                self.error = str(error)
            self.status("FAILED", error_type=type(error).__name__, message=str(error))
        finally:
            if self.error or self.stopping.is_set():
                self._release()

    def _initialize(self):
        from opensubsurface.adapters.local_sources import LocalSources
        from opensubsurface.desktop_lifecycle import ViewerLease
        from opensubsurface.service import Service
        from opensubsurface.setup import ensure_viewer

        self.lease = ViewerLease(self.home).acquire()
        if self.stopping.is_set():
            return
        self.service = Service(self.home)
        self.status("SERVICE_READY", message="Database migrations complete")
        if os.environ.get("KANYSH_VARIANT") == "gpu":
            from opensubsurface.execution.device import cuda_runtime

            runtime = cuda_runtime()
            warnings = (
                [] if runtime["cuda_available"] else ["CUDA unavailable; GPU extension is running on CPU"]
            )
            self.status("SERVICE_READY", runtime=runtime, warnings=warnings)
        folder = os.environ.get("KANYSH_SOURCE_FOLDER", "")
        if folder and not folder.startswith("${"):
            path = Path(os.path.expandvars(os.path.expanduser(folder)))
            LocalSources(self.service.store).register(path.name or "Model folder", path)
        if self.stopping.is_set():
            return
        result = ensure_viewer(
            self.service,
            port=8767 if os.environ.get("KANYSH_VARIANT") == "gpu" else 8765,
            managed=True,
            first_run=True,
            open_browser=os.environ.get("KANYSH_OPEN_BROWSER", "1") != "0",
        )
        self.status("VIEWER_" + result["status"], viewer=result, viewer_url=result.get("url"))
        if result["status"] not in ("RUNNING", "ALREADY_RUNNING"):
            raise RuntimeError("Viewer failed to start; inspect " + str(self.home / "viewer.log"))

    def require_ready(self):
        if self.error is not None:
            raise StartupError("FAILED", self.error, self.stage, self.home)
        if not self.ready.is_set():
            raise StartupError("STARTING", "Kanysh is starting; retry in 2 seconds", self.stage, self.home)
        return self.service

    def _release(self):
        if self.service:
            self.service.close()
            self.service = None
        if self.lease:
            self.lease.release()
            self.lease = None

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=2)
        if not self.thread.is_alive():
            self._release()
        # A daemon thread cannot hold up host shutdown. Its lease is tied to this
        # PID/create_time; the independent viewer reaps it if this process exits.


def run():
    from opensubsurface.mcp.server import create_mcp

    runtime = DesktopRuntime(configured_home())

    @asynccontextmanager
    async def lifespan(server):
        runtime.start()
        try:
            yield {}
        finally:
            runtime.close()

    create_mcp(runtime, profile="agent", lifespan=lifespan).run(transport="stdio")


if __name__ == "__main__":
    run()
