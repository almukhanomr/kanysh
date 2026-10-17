import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil


def terminate_group(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def run_isolated(directory, timeout):
    directory = Path(directory)
    if (directory / "cancel").exists():
        return {"ok": False, "error": {"code": "CANCELLED", "message": "Задание отменено"}}
    # No provider, LLM or control-plane credentials in compute subprocess.
    env = {
        k: os.environ[k]
        for k in (
            "PATH",
            "VIRTUAL_ENV",
            "LANG",
            "PYTHONPATH",
            "OPENSUBSURFACE_FLOW_EXECUTABLE",
            "CUDA_VISIBLE_DEVICES",
        )
        if k in os.environ
    }
    env.update(
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        GEMPY_GPU_FALLBACK="False",
        PYTHONUNBUFFERED="1",
    )
    cache = directory.parent.parent / "cache"
    (cache / "matplotlib").mkdir(parents=True, exist_ok=True)
    env["MPLCONFIGDIR"] = str(cache / "matplotlib")
    env["PYVISTA_USERDATA_PATH"] = str(cache / "pyvista")
    started = time.monotonic()
    with (directory / "worker.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "opensubsurface.execution.worker", str(directory)],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
        (directory / "pid").write_text(str(process.pid))
        try:
            identity = dict(pid=process.pid, create_time=psutil.Process(process.pid).create_time())
            (directory / "process.json").write_text(json.dumps(identity))
        except psutil.NoSuchProcess:
            pass
        while process.poll() is None:
            cancelled = (directory / "cancel").exists()
            if cancelled or time.monotonic() - started > timeout:
                terminate_group(process)
                return dict(
                    ok=False,
                    error=dict(
                        code="CANCELLED" if cancelled else "TIMEOUT",
                        message="Вычислительный процесс остановлен",
                        field="",
                        remediation="",
                    ),
                )
            time.sleep(0.1)
    result_path = directory / "result.json"
    if not result_path.is_file():
        return dict(
            ok=False,
            error=dict(
                code="WORKER_CRASH",
                message="Worker не опубликовал результат",
                field="",
                remediation="Проверьте worker.log",
            ),
        )
    return json.loads(result_path.read_text())


def stop_orphan(directory):
    """On restart, match PID creation time and full worker argv before sending a signal."""
    directory = Path(directory)
    identity_file = directory / "process.json"
    if not identity_file.is_file():
        return False
    try:
        identity = json.loads(identity_file.read_text())
        process = psutil.Process(identity["pid"])
        args = process.cmdline()
        if (
            abs(process.create_time() - identity["create_time"]) > 0.01
            or "opensubsurface.execution.worker" not in args
            or str(directory) not in args
        ):
            return False
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except psutil.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
        return True
    except (psutil.NoSuchProcess, ProcessLookupError):
        return False
