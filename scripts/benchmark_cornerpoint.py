"""Actual 20M-cell materialized corner-point import and independent analytic verification."""

import argparse
import json
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import psutil
import zarr

from opensubsurface.adapters.eclipse_import import import_deck
from opensubsurface.adapters.local_sources import LocalSources, revision
from opensubsurface.service import Service


def worker(base):
    source = base / "input"
    source.mkdir()
    nx, ny, nz = 500, 400, 100
    cells = nx * ny * nz
    path = source / "MODEL.DATA"
    with path.open("w") as f:
        f.write(f"RUNSPEC\nDIMENS\n{nx} {ny} {nz} /\nMETRIC\nGRID\nCOORD\n")
        for j in range(ny + 1):
            for i in range(nx + 1):
                f.write(f"{i * 10} {j * 20} 0 {i * 10} {j * 20} {nz * 5}\n")
        f.write("/\nZCORN\n")
        for k in range(nz):
            for z in (k * 5, (k + 1) * 5):
                f.write(f"{4 * nx * ny}*{z}\n")
        f.write("/\n")
        for key, value in {
            "ACTNUM": 1,
            "PORO": 0.2,
            "NTG": 0.8,
            "PERMX": 100,
            "PERMZ": 10,
            "SWAT": 0.25,
            "FIPNUM": 1,
            "SATNUM": 1,
            "EQLNUM": 1,
        }.items():
            f.write(f"{key}\n{cells}*{value} /\n")
        f.write("END\n")
    service = Service(base / "home")
    src = LocalSources(service.store).register("20M analytic benchmark", source)
    out = base / "output"
    out.mkdir()
    started = time.monotonic()
    p = dict(
        path=path.name,
        file_revision=revision(path.stat()),
        length_unit="m",
        z_direction="down",
        defaults={},
        region_field="FIPNUM",
        crs="LOCAL_METRIC",
        vertical_datum="SYNTHETIC",
        assumptions=["Synthetic regular corner-point benchmark; explicitly generated field values"],
        block_cells=16384,
    )
    _, summary, files = import_deck(dict(source=src), p, out)
    imported = time.monotonic() - started
    total = 0.0
    with zarr.ZipStore(str(files["grid.zip"]), mode="r") as store:
        g = zarr.open_group(store=store)
        for start in range(0, cells, 16384):
            end = min(cells, start + 16384)
            ids = np.arange(start, end)
            origin = np.column_stack((ids % nx * 10, (ids // nx) % ny * 20, -(ids // (nx * ny)) * 5))
            offsets = np.array(
                [
                    [0, 0, 0],
                    [10, 0, 0],
                    [0, 20, 0],
                    [10, 20, 0],
                    [0, 0, -5],
                    [10, 0, -5],
                    [0, 20, -5],
                    [10, 20, -5],
                ]
            )
            c = g["corners"][start:end]
            np.testing.assert_array_equal(c, origin[:, None, :] + offsets)
            # Independent box-volume formula, not the production tetrahedral integral.
            total += float(np.prod(np.ptp(c, axis=1), axis=1).sum())
            for key, value in {
                "active": 1,
                "phi": 0.2,
                "ntg": 0.8,
                "sw": 0.25,
                "zones": 1,
                "permeability_md": 100,
                "kz_ratio": 0.1,
            }.items():
                np.testing.assert_array_equal(g[key][start:end], np.full(end - start, value))
    assert total == cells * 1000
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    result = dict(
        status="PASS",
        cells=cells,
        shape=[nx, ny, nz],
        input_bytes=path.stat().st_size,
        source_encoding="Real DATA text with standard RLE; 160M ZCORN values expanded to disk",
        materialized_corner_bytes=cells * 8 * 3 * 8,
        active_cells=summary["active_cells"],
        independent_full_geometry_and_properties="PASS",
        analytic_grv_m3=total,
        import_seconds=imported,
        total_seconds=time.monotonic() - started,
        worker_peak_rss_bytes=peak,
        rss_limit_bytes=2 * 1024**3,
        ram_check="PASS" if peak <= 2 * 1024**3 else "FAIL",
        scope="20M-cell regular COORD/ZCORN import; no claims for simulator initialization or every fault geometry",
    )
    (base / "result.json").write_text(json.dumps(result, indent=2))
    service.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    with tempfile.TemporaryDirectory(prefix="cornerpoint-20m-") as temporary:
        base = Path(temporary)
        process = subprocess.Popen([sys.executable, __file__, "--worker", str(base)])
        maximum = 0
        while process.poll() is None:
            try:
                root = psutil.Process(process.pid)
                maximum = max(
                    maximum,
                    sum(
                        p.memory_info().rss for p in [root, *root.children(recursive=True)] if p.is_running()
                    ),
                )
            except psutil.Error:
                pass
            time.sleep(0.02)
        if process.returncode:
            raise SystemExit(process.returncode)
        result = json.loads((base / "result.json").read_text())
        result["sampled_process_tree_rss_bytes"] = maximum
        result["ram_check"] = (
            "PASS" if max(maximum, result["worker_peak_rss_bytes"]) <= result["rss_limit_bytes"] else "FAIL"
        )
        Path("docs/benchmark-cornerpoint-20m.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
