"""Worker-side progress: throttled progress.json in the attempt directory plus a worker.log line.

Only the isolated worker writes it; the control plane reads it for job_status/calculation_status.
Outside a worker (tests, direct adapter calls) reporting is a no-op.
"""

import json
import os
import time
from pathlib import Path

_state = dict(directory=None, started=None, last=0.0)


def attach(directory):
    _state.update(directory=Path(directory), started=time.monotonic(), last=0.0)


def log(message):
    if _state["directory"] is not None:
        print(f"[{time.monotonic() - _state['started']:8.2f}s] {message}", flush=True)


def report(fraction, message=None, force=False):
    directory = _state["directory"]
    if directory is None:
        return
    now = time.monotonic()
    if not force and now - _state["last"] < 1.0:
        return
    _state["last"] = now
    fraction = min(max(float(fraction), 0.0), 1.0)
    elapsed = now - _state["started"]
    eta = round(elapsed * (1 - fraction) / fraction, 1) if fraction > 0 else None
    record = dict(progress=round(fraction, 4), eta_s=eta, elapsed_s=round(elapsed, 2), message=message)
    temp = directory / "progress.json.tmp"
    temp.write_text(json.dumps(record), encoding="utf-8")
    for attempt in range(6):
        try:
            os.replace(temp, directory / "progress.json")
            break
        except PermissionError:
            # A Windows client may briefly hold the old JSON open while polling.
            if os.name != "nt" or attempt == 5:
                raise
            time.sleep(0.01 * 2**attempt)
    log(f"progress {fraction:.0%}" + (f" {message}" if message else ""))
