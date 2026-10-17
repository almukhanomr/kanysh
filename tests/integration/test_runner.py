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
