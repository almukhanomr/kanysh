"""Small, cross-process leases for Desktop-owned viewers; no database or scientific imports."""

import json
import os
import time
import uuid
from pathlib import Path

import portalocker
import psutil


def identity(pid=None):
    process = psutil.Process(pid or os.getpid())
    return dict(pid=process.pid, created=process.create_time())


def alive(record):
    try:
        process = psutil.Process(record["pid"])
        return (
            process.create_time() == record["created"]
            and process.is_running()
            and process.status() != psutil.STATUS_ZOMBIE
        )
    except (KeyError, ValueError, psutil.Error):
        return False


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(value), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def live_leases(home):
    """Caller holds desktop-leases.lock. PID creation time protects against PID reuse."""
    live = []
    for path in (Path(home) / "desktop-leases").glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        if alive(record):
            live.append(record)
        else:
            path.unlink(missing_ok=True)
    return live


class ViewerLease:
    def __init__(self, home):
        self.home = Path(home)
        self.path = self.home / "desktop-leases" / (uuid.uuid4().hex + ".json")

    def acquire(self):
        with portalocker.Lock(self.home / "desktop-leases.lock", mode="a", timeout=120):
            self.path.parent.mkdir(exist_ok=True)
            write_json(self.path, identity())
        return self

    def release(self):
        with portalocker.Lock(self.home / "desktop-leases.lock", mode="a", timeout=120):
            self.path.unlink(missing_ok=True)


def monitor(home, stopping, shutdown):
    """Stop only this managed viewer, after its final live Desktop client disappears.

    A standalone CLI viewer never starts this monitor. A second Desktop client has its
    own independent lease, including while its service is still initializing.
    """
    home = Path(home)
    empty_since = None
    while not stopping.wait(0.5):
        if not home.exists():
            shutdown()
            return
        with portalocker.Lock(home / "desktop-leases.lock", mode="a", timeout=120):
            live = live_leases(home)
        if live:
            empty_since = None
            continue
        empty_since = empty_since or time.monotonic()
        if time.monotonic() - empty_since < 2:
            continue
        with portalocker.Lock(home / "viewer-start.lock", mode="a", timeout=120):
            with portalocker.Lock(home / "desktop-leases.lock", mode="a", timeout=120):
                if live_leases(home):
                    continue
                write_json(home / "viewer-process.json", dict(identity(), stopping=True, managed=True))
                shutdown()
                return
