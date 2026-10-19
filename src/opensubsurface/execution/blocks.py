"""Bounded, spawn-safe process mapping with a fixed block reduction order.

Children open immutable storage themselves; geometry is not sent through IPC.
The same callable and partitions are used by serial and parallel execution.
"""

import atexit
import json
import multiprocessing
import os
from collections import deque
from contextlib import ExitStack
from contextvars import ContextVar
from multiprocessing.connection import wait

import numpy as np

from opensubsurface.execution import progress
from opensubsurface.execution.resources import plan

settings = ContextVar("block_execution", default={})
_session = ContextVar("block_storage", default=None)


def _initialize():
    from numcodecs import blosc

    blosc.set_nthreads(1)
    stack = ExitStack()
    _session.set((stack, {}))
    atexit.register(stack.close)


def model_layout(obj):
    from opensubsurface.adapters.model_arrays import opened

    if _session.get() is None:
        _initialize()
    stack, models = _session.get()
    key = (tuple(sorted(obj["paths"].items())), json.dumps(obj["summary"], sort_keys=True))
    if key not in models:
        group, order = stack.enter_context(opened(obj))
        names = group.array_keys() if hasattr(group, "array_keys") else group
        models[key] = group, order, {name: group[name] for name in names}
    return models[key]


def model_group(obj):
    group, order, _ = model_layout(obj)
    return group, order


def read_block(obj, start, count, include_corners=True):
    from opensubsurface.adapters.model_arrays import cartesian_corners

    _, order, arrays = model_layout(obj)
    data = {name: np.asarray(array[start : start + count]) for name, array in arrays.items()}
    if include_corners and "corners" not in data:
        data["corners"] = cartesian_corners(obj, np.arange(start, start + count), order)
    return start, data, order


def _apply(function, obj, start, count, args, include_corners):
    return function(*read_block(obj, start, count, include_corners), *args)


def _cells_message(done, cells):
    # Shown to users in job_status: report cells, not private helper names like "_scan_block".
    return f"{min(done, cells):,} of {cells:,} cells processed"


def mapped(obj, function, *args, execution=None, include_corners=True):
    import math

    from opensubsurface.adapters.model_arrays import iterate, opened

    execution = settings.get() if execution is None else execution
    if execution.get("resolved_device") == "cuda":
        from opensubsurface.errors import require

        require(
            execution.get("max_workers") in (None, 1),
            "INVALID_ARGUMENTS",
            "CUDA blocks use one coordinator per device",
            "execution.max_workers",
            "Set max_workers=1 or omit it for CUDA",
        )
        execution = dict(execution, max_workers=1)
    cells = math.prod(obj["summary"]["grid"]["shape"])
    with opened(obj) as (group, _):
        step = min(a.chunks[0] for _, a in group.arrays()) if hasattr(group, "arrays") else 16384
    config = plan(cells, step, execution.get("max_workers"))
    workers = config["max_workers"]
    progress.log(
        f"block plan: max_workers={workers} block_cells={step} "
        f"estimated_peak_bytes={config['estimated_peak_bytes']}"
    )
    if workers == 1:
        with ExitStack() as stack:
            token = _session.set((stack, {}))
            try:
                for start, data, order in iterate(obj, include_corners=include_corners):
                    result = function(start, data, order, *args)
                    done = start + len(data["active"])
                    progress.report(done / cells, _cells_message(done, cells))
                    yield result
            finally:
                _session.reset(token)
        return
    # Spawn imports NumPy before the initializer: set the environment before spawning.
    variables = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLOSC_NTHREADS")
    previous = {k: os.environ.get(k) for k in variables}
    try:
        for key in variables:
            os.environ[key] = "1"
        yield from _parallel(obj, function, args, cells, step, workers, include_corners)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _serve(connection, function, obj, args, include_corners):
    """One channel per process: no shared Queue semaphore or feeder thread."""
    from opensubsurface.errors import DomainError

    _initialize()
    try:
        while True:
            item = connection.recv()
            if item is None:
                return
            start, count = item
            try:
                answer = _apply(function, obj, start, count, args, include_corners)
                connection.send((start, True, answer))
            except DomainError as error:
                connection.send((start, False, error.as_dict()))
            except Exception as error:
                import traceback

                traceback.print_exc()
                failure = DomainError(
                    "COMPUTE_FAILED",
                    "Block computation failed: " + type(error).__name__,
                    "",
                    "Inspect worker.log",
                    dict(block_start=start),
                )
                connection.send((start, False, failure.as_dict()))
    finally:
        state = _session.get()
        if state is not None:
            state[0].close()
        connection.close()


def _parallel(obj, function, args, cells, step, workers, include_corners):
    """At most 2N busy/ready blocks, reduced by immutable offset.

    Pipe messages to children contain only offset/count. Function, metadata and
    scenario declarations are sent once at spawn. EOF/process exit always fails
    the operation; no automatic resubmission or change of numerical backend.
    """
    from opensubsurface.errors import DomainError

    context = multiprocessing.get_context("spawn")
    processes, channels, owners = [], [], {}
    complete = False
    expected, ready, busy = 0, {}, {}
    offsets = iter(range(0, cells, step))

    def crash(connection, start, error):
        process = owners.get(connection)
        return DomainError(
            "WORKER_CRASH",
            "A block process or its IPC channel failed",
            "execution.max_workers",
            "Inspect worker.log and child exit codes; check RAM and process limits",
            dict(
                block_start=start,
                pid=process.pid if process else None,
                exitcode=process.exitcode if process else None,
                ipc_error=type(error).__name__,
            ),
        )

    try:
        for _ in range(workers):
            parent, child = context.Pipe(duplex=True)
            process = context.Process(target=_serve, args=(child, function, obj, args, include_corners))
            try:
                process.start()
            except OSError as error:
                parent.close()
                child.close()
                raise DomainError(
                    "INSUFFICIENT_MEMORY"
                    if getattr(error, "winerror", None) in (8, 14, 1455)
                    else "WORKER_CRASH",
                    "Unable to start a block process",
                    "execution.max_workers",
                    "Reduce max_workers and check RAM, commit/pagefile and process limits",
                    dict(os_error=str(error)),
                ) from error
            child.close()
            processes.append(process)
            channels.append(parent)
            owners[parent] = process
        idle = deque(channels)

        def dispatch():
            while idle and len(busy) + len(ready) < 2 * workers:
                start = next(offsets, None)
                if start is None:
                    break
                connection = idle.popleft()
                try:
                    connection.send((start, min(step, cells - start)))
                except (OSError, EOFError) as error:
                    raise crash(connection, start, error) from error
                busy[connection] = start

        dispatch()
        while expected < cells:
            if expected not in ready:
                if not busy:
                    raise DomainError("WORKER_CRASH", "No process owns the next expected block")
                for connection in wait(list(busy), timeout=0.5):
                    start = busy.pop(connection)
                    try:
                        returned, ok, answer = connection.recv()
                    except (OSError, EOFError) as error:
                        raise crash(connection, start, error) from error
                    if returned != start:
                        raise DomainError("INTEGRITY_ERROR", "Block channel returned an unexpected offset")
                    ready[start] = ok, answer
                    idle.append(connection)
                for connection, start in busy.items():
                    if owners[connection].exitcode is not None:
                        raise crash(connection, start, EOFError())
                dispatch()
            while expected in ready:
                ok, answer = ready.pop(expected)
                if not ok:
                    raise DomainError(**answer)
                progress.report(min(expected + step, cells) / cells, _cells_message(expected + step, cells))
                expected += step
                dispatch()
                yield answer
        complete = True
    finally:
        if complete:
            for connection in channels:
                try:
                    connection.send(None)
                except (OSError, EOFError):
                    pass
        for process in processes:
            if not complete and process.is_alive():
                process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        for connection in channels:
            connection.close()
        exits = {str(p.pid): p.exitcode for p in processes if p.exitcode != 0}
        for process in processes:
            if not process.is_alive():
                process.close()
        if complete and exits:
            raise DomainError(
                "WORKER_CRASH", "Block processes failed during shutdown", details=dict(child_exit_codes=exits)
            )
