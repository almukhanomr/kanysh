"""Read-only startup/runtime diagnostics usable while the workstation is still starting.

Never imports torch (that is what may be slow), never returns environment variables,
tokens or file contents other than Kanysh's own startup/viewer log tails.
"""

import importlib.metadata
import json
import platform
import re
import sys
from pathlib import Path

SECRET = re.compile(r"(?i)(token|password|secret|authorization|api[_-]?key)(\s*[=:]\s*|\s+)\S+")


def _tail(path, lines):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 262144))
        text = stream.read().decode("utf-8", errors="replace")
    return [SECRET.sub(r"\1\2<redacted>", line) for line in text.splitlines()[-lines:]]


def _versions():
    versions = dict(python=platform.python_version(), platform=platform.platform())
    for name in ("kanysh-basic", "numpy", "scipy", "torch", "gempy", "mcp", "xtgeo", "pydantic"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def diagnostics(target, p):
    """target is a DesktopRuntime (stdio extension) or a Service (CLI/REST)."""
    runtime = target if hasattr(target, "require_ready") else None
    service = getattr(runtime, "service", None) if runtime else target
    home = Path(runtime.home if runtime else service.store.root)
    startup = None
    if runtime:
        import time

        with runtime.lock:
            details = dict(runtime.details)
            startup = dict(
                stage=runtime.stage,
                substage=runtime.substage,
                waiting_for=details.get("waiting_for"),
                elapsed_s=round(time.monotonic() - runtime.started, 3),
                substage_seconds=dict(runtime.timings),
                service_ready=runtime.service_ready.is_set(),
                ready=runtime.ready.is_set(),
                error=runtime.error,
            )
        from opensubsurface.desktop import EARLY_OPERATIONS, WAITING_FOR

        startup["waiting_for"] = WAITING_FOR.get(startup["substage"])
        startup["available_before_ready"] = sorted(EARLY_OPERATIONS | {"diagnostics"})
        cuda = details.get("runtime")
    else:
        cuda = None
    if cuda is None and "torch" in sys.modules:
        from opensubsurface.execution.device import cuda_runtime

        cuda = cuda_runtime()
    viewer = dict(url=None, process=None, log_tail=_tail(home / "viewer.log", 20))
    try:
        viewer["process"] = json.loads((home / "viewer-process.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if service is not None:
        from opensubsurface.viewer_links import base_url

        try:
            viewer["url"] = base_url(service)
        except Exception as error:  # Diagnostics must still answer if the store is locked.
            viewer["url_error"] = type(error).__name__
    if viewer["url"]:
        viewer["port"] = int(viewer["url"].rsplit(":", 1)[1])
    return dict(
        home=str(home),
        startup=startup,
        startup_log=str(home / "startup.log"),
        startup_log_tail=_tail(home / "startup.log", p["lines"]),
        versions=_versions(),
        cuda=cuda if cuda is not None else dict(status="NOT PROBED YET", note="probed during cuda_warmup"),
        viewer=viewer,
        secrets="none returned; environment variables and tokens are never included",
    )
