import json
import platform
import time
from pathlib import Path

import numpy as np
import psutil

from opensubsurface.domain.numerics import volumes
from opensubsurface.persistence.store import now


def benchmark(output):
    output = Path(output)
    output.mkdir(exist_ok=True, parents=True)
    rows = []
    for shape in [(50, 50, 30), (100, 100, 100)]:
        start = time.perf_counter()
        arrays = dict(
            active=np.ones(shape, bool),
            zones=np.ones(shape, np.int32),
            phi=np.full(shape, 0.2),
            ntg=np.full(shape, 0.8),
            sw=np.full(shape, 0.25),
            permeability_md=np.full(shape, 100.0),
        )
        prepared = time.perf_counter()
        result = volumes(arrays, dict(shape=shape, extent=[0, 1000, 0, 1000, -1020, -1000]), [1], -1020, 1.2)
        end = time.perf_counter()
        error = abs(result["values"]["STOIIP"] - 2e6) / 2e6
        rows.append(
            dict(
                shape=shape,
                cells=int(np.prod(shape)),
                preparation_seconds=prepared - start,
                compute_seconds=end - prepared,
                full_wall_seconds=end - start,
                relative_error=error,
                process_rss_bytes=psutil.Process().memory_info().rss,
                precision="float64",
                backend="numpy-cpu",
                scope="Static-volume kernel only, not GemPy/OPM or application cold start",
            )
        )
    report = dict(
        timestamp=now(),
        hardware=dict(
            platform=platform.platform(),
            machine=platform.machine(),
            processor=platform.processor(),
            logical_cpus=psutil.cpu_count(),
            ram_bytes=psutil.virtual_memory().total,
        ),
        numpy=np.__version__,
        rows=rows,
        cuda="NOT RUN",
        opm="NOT RUN",
    )
    (output / "cpu.json").write_text(json.dumps(report, indent=2))
    return report
