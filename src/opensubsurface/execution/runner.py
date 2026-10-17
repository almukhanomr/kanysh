import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil


def process_options():
    return (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )


def terminate_tree(process, timeout=3):
    """Snapshot descendants before termination; psutil guards against PID reuse."""
    try:
        descendants = process.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    targets = [*reversed(descendants), process]
    for target in targets:
        try:
            target.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(targets, timeout=timeout)
    for target in alive:
        try:
            target.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=5)
    require_stopped = [p for p in alive if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
    if require_stopped:
        raise RuntimeError("Worker process tree did not stop")


def terminate_group(process):
    if process.poll() is not None:
        return
    try:
        terminate_tree(psutil.Process(process.pid))
    except psutil.NoSuchProcess:
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
            "SystemRoot",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "APPDATA",
            "USERPROFILE",
        )
        if k in os.environ
    }
    env.update(
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        GEMPY_GPU_FALLBACK="False",
        PYTHONUNBUFFERED="1",
        PYTHONUTF8="1",
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
            **process_options(),
            env=env,
        )
        (directory / "pid").write_text(str(process.pid), encoding="utf-8")
        try:
            identity = dict(pid=process.pid, create_time=psutil.Process(process.pid).create_time())
            (directory / "process.json").write_text(json.dumps(identity), encoding="utf-8")
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
    return json.loads(result_path.read_text(encoding="utf-8"))


def stop_orphan(directory):
    """On restart, match PID creation time and full worker argv before sending a signal."""
    directory = Path(directory)
    identity_file = directory / "process.json"
    if not identity_file.is_file():
        return False
    try:
        identity = json.loads(identity_file.read_text(encoding="utf-8"))
        process = psutil.Process(identity["pid"])
        args = process.cmdline()
        if (
            process.create_time() != identity["create_time"]
            or "opensubsurface.execution.worker" not in args
            or not any(
                os.path.normcase(os.path.abspath(arg)) == os.path.normcase(str(directory.resolve()))
                for arg in args
            )
        ):
            return False
        terminate_tree(process)
        return True
    except (psutil.NoSuchProcess, ProcessLookupError):
        return False
