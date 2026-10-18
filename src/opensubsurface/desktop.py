"""Fast stdio transport with background workstation initialization and shared viewer leases."""

import json
import os
import sys
import threading
import time
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


# Read-only discovery that needs neither the shared controller, CUDA nor the viewer.
# They run on this client's own Service as soon as SERVICE_READY; everything else waits.
EARLY_OPERATIONS = {
    "start",
    "source_list",
    "source_scan",
    "source_inspect",
    "folder_assess",
    "project_list",
    "project_inspect",
    "artifact_inspect",
    "scene_inspect",
    "job_status",
    "job_logs",
    "calculation_status",
}
WAITING_FOR = {
    "viewer_lease": "shared viewer lease (another Kanysh client may be starting)",
    "database": "metadata database migrations and service imports",
    "cuda_warmup": "PyTorch import and CUDA device initialization (GPU edition)",
    "viewer_start": "local viewer/controller process and its /health endpoint",
}


class StartupError(DomainError):
    def __init__(self, code, message, stage, home, substage=None, elapsed_s=None, waiting_for=None):
        remediation = (
            "Retry after retry_after_seconds. Read-only discovery (source_list, folder_assess, project_list, "
            "job_status, ...) is available as soon as stage is SERVICE_READY. Call diagnostics for startup.log."
            if code == "STARTING"
            else "Call diagnostics for the startup.log tail, then restart the MCP server."
        )
        super().__init__(code, message, remediation=remediation)
        self.stage, self.home = stage, home
        self.substage, self.elapsed_s, self.waiting_for = substage, elapsed_s, waiting_for

    def as_dict(self):
        return dict(
            super().as_dict(),
            stage=self.stage,
            substage=self.substage,
            elapsed_s=self.elapsed_s,
            waiting_for=self.waiting_for,
            retry_after_seconds=2 if self.code == "STARTING" else None,
            log=str(self.home / "startup.log"),
            home=str(self.home),
        )


class DesktopRuntime:
    def __init__(self, home, initialize=None):
        self.home = Path(home).resolve()
        self.stage = "STARTING"
        self.substage = None
        self.started = time.monotonic()
        self.substage_started = self.started
        self.error = None
        self.service = None
        self.lease = None
        self.details = {}
        self.timings = {}
        self.service_ready = threading.Event()
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.lock = threading.RLock()
        self.initialize = initialize or self._initialize
        self.thread = threading.Thread(target=self._background, daemon=True, name="kanysh-startup")

    def enter(self, substage):
        """Record a startup sub-stage; its duration is logged when the next one begins."""
        with self.lock:
            now = time.monotonic()
            if self.substage:
                self.timings[self.substage] = round(now - self.substage_started, 3)
            self.substage, self.substage_started = substage, now
        if substage:
            self.status(self.stage, message="Waiting for " + WAITING_FOR[substage])

    def status(self, stage, **details):
        from opensubsurface.desktop_lifecycle import write_json

        with self.lock:
            self.stage = stage
            self.details.update(details)
            record = dict(
                self.details,
                stage=stage,
                substage=self.substage,
                waiting_for=WAITING_FOR.get(self.substage),
                elapsed_s=round(time.monotonic() - self.started, 3),
                substage_seconds=dict(self.timings),
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
                self.enter(None)
                self.status("MCP_READY", message="Local services ready; MCP transport remains available")
                self.service_ready.set()
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

        self.enter("viewer_lease")
        self.lease = ViewerLease(self.home).acquire()
        if self.stopping.is_set():
            return
        self.enter("database")
        self.service = Service(self.home)
        folder = os.environ.get("KANYSH_SOURCE_FOLDER", "")
        if folder and not folder.startswith("${"):
            path = Path(os.path.expandvars(os.path.expanduser(folder)))
            LocalSources(self.service.store).register(path.name or "Model folder", path)
        # Discovery is usable from here; CUDA warm-up and the viewer are not required for it.
        gpu = os.environ.get("KANYSH_VARIANT") == "gpu"
        self.enter("cuda_warmup" if gpu else "viewer_start")
        self.status("SERVICE_READY", message="Database ready; read-only discovery available")
        self.service_ready.set()
        if gpu:
            from opensubsurface.execution.device import cuda_runtime

            runtime = cuda_runtime()
            warnings = (
                [] if runtime["cuda_available"] else ["CUDA unavailable; GPU extension is running on CPU"]
            )
            self.status("SERVICE_READY", runtime=runtime, warnings=warnings)
            self.enter("viewer_start")
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

    def require_ready(self, operation=None):
        with self.lock:
            stage, substage = self.stage, self.substage
            elapsed = round(time.monotonic() - self.started, 3)
        if self.error is not None:
            raise StartupError("FAILED", self.error, stage, self.home, substage, elapsed)
        if self.ready.is_set():
            return self.service
        if self.service_ready.is_set() and operation in EARLY_OPERATIONS:
            return self.service
        raise StartupError(
            "STARTING",
            f"Kanysh is starting ({substage or stage}, {elapsed:.0f} s); "
            + (
                f"{operation} needs the full controller; retry in 2 seconds"
                if self.service_ready.is_set()
                else "retry in 2 seconds"
            ),
            stage,
            self.home,
            substage,
            elapsed,
            WAITING_FOR.get(substage) or "local service initialization",
        )

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
