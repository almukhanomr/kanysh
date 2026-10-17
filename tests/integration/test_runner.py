import subprocess
import sys
import threading
import time

import pytest

from opensubsurface.execution import runner


@pytest.mark.parametrize("cancel", [True, False])
def test_cancellation_kills_process_group(tmp_path, monkeypatch, cancel):
    original = subprocess.Popen
    processes = []

    def fake_popen(args, **kwargs):
        process = original([sys.executable, "-c", "import time; time.sleep(120)"], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    result = []
    thread = threading.Thread(
        target=lambda: result.append(runner.run_isolated(str(tmp_path), 60 if cancel else 1))
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not (tmp_path / "pid").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    started = time.monotonic()
    if cancel:
        (tmp_path / "cancel").touch()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert time.monotonic() - started < 10
    assert result[0]["error"]["code"] == ("CANCELLED" if cancel else "TIMEOUT")
    assert processes[0].poll() is not None


@pytest.mark.parametrize("cancel", [True, False])
def test_cancel_and_timeout_stop_real_descendant(tmp_path, monkeypatch, cancel):
    import json

    import psutil

    original = subprocess.Popen
    child_file = tmp_path / "child.json"
    script = (
        "import subprocess,sys,time,json; from pathlib import Path; import psutil; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
        f"Path({str(child_file)!r}).write_text(json.dumps(dict(pid=p.pid, created=psutil.Process(p.pid).create_time()))); "
        "time.sleep(120)"
    )
    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda args, **kw: original([sys.executable, "-c", script], **kw)
    )
    result = []
    thread = threading.Thread(
        target=lambda: result.append(runner.run_isolated(tmp_path, 60 if cancel else 2))
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not child_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert child_file.exists()
        if cancel:
            (tmp_path / "cancel").touch()
        thread.join(15)
        assert not thread.is_alive()
        assert result[0]["error"]["code"] == ("CANCELLED" if cancel else "TIMEOUT")
        child = json.loads(child_file.read_text())
        try:
            process = psutil.Process(child["pid"])
            assert process.create_time() != child["created"] or process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
    finally:
        (tmp_path / "cancel").touch()
        thread.join(15)


def test_orphan_identity_mismatch_never_signals_process(tmp_path):
    import json

    import psutil

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(120)",
            "opensubsurface.execution.worker",
            str(tmp_path),
        ],
        **runner.process_options(),
    )
    try:
        created = psutil.Process(process.pid).create_time()
        identity = tmp_path / "process.json"
        identity.write_text(json.dumps(dict(pid=process.pid, create_time=created + 10)))
        assert runner.stop_orphan(tmp_path) is False and process.poll() is None
        identity.write_text(json.dumps(dict(pid=process.pid, create_time=created)))
        assert runner.stop_orphan(tmp_path) is True
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
