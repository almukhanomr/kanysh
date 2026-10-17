"""Actual >15 GiB Cartesian input, isolated workers, measured RSS and analytical checks.

No sparse files, virtual arrays or sampled calculation. Temporary inputs/results are removed
unless --keep-data is set; the complete machine-readable benchmark evidence is retained.
"""

import argparse
import json
import math
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import psutil

from opensubsurface.adapters.large_grid import FORMAT, UNITS
from opensubsurface.adapters.local_sources import LocalSources, path_revision
from opensubsurface.execution.provenance import fingerprint
from opensubsurface.service import Service, ref


class Measurement:
    def __init__(self, directory=None):
        self.directory = directory

    def __enter__(self):
        self.process = psutil.Process()
        self.peak = 0
        self.samples = 0
        self.disk_peak = 0
        self.stop = threading.Event()
        self.started = time.monotonic()

        def poll():
            while not self.stop.is_set():
                rss = 0
                for process in [self.process] + self.process.children(recursive=True):
                    try:
                        rss += process.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                self.peak = max(self.peak, rss)
                if self.directory:
                    allocated = 0
                    for path in self.directory.rglob("*"):
                        try:
                            info = path.stat()
                            allocated += info.st_blocks * 512
                        except FileNotFoundError:
                            pass
                    self.disk_peak = max(self.disk_peak, allocated)
                self.samples += 1
                self.stop.wait(0.02)

        self.thread = threading.Thread(target=poll, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.result = dict(
            elapsed_seconds=time.monotonic() - self.started,
            peak_process_tree_rss_bytes=self.peak,
            rss_sample_count=self.samples,
            sampled_workspace_allocated_peak_bytes=self.disk_peak,
        )


def generate(folder, shape, block):
    cells = math.prod(shape)
    arrays = {}
    constants = dict(active=1, zones=1, phi=0.2, ntg=0.8, sw=0.25, kz_ratio=0.1)
    rng = np.random.default_rng(42)
    for name in UNITS:
        path = folder / (name + ".npy")
        dtype = np.dtype("bool" if name == "active" else "int32" if name == "zones" else "float64")
        with path.open("wb") as stream:
            np.lib.format.write_array_header_2_0(
                stream, dict(descr=dtype.str, fortran_order=False, shape=tuple(shape))
            )
            for start in range(0, cells, block):
                count = min(block, cells - start)
                data = (
                    rng.uniform(90, 110, count)
                    if name == "permeability_md"
                    else np.full(count, constants[name], dtype=dtype)
                )
                stream.write(data.tobytes(order="C"))
            stream.flush()
            import os

            os.fsync(stream.fileno())
        arrays[name] = dict(path=path.name, file_revision=path_revision(path))
        print("Wrote", name, path.stat().st_size, "bytes", flush=True)
    grid = dict(shape=shape, extent=[0, float(shape[0]), 0, float(shape[1]), -float(shape[2]), 0])
    manifest = dict(
        format=FORMAT,
        grid=grid,
        crs="LOCAL_METRIC",
        vertical_datum="SYNTHETIC",
        z_direction="up",
        units=UNITS,
        arrays=arrays,
    )
    path = folder / "model.json"
    path.write_text(json.dumps(manifest))
    return path, grid


def run(args):
    cells = math.prod(args.shape)
    raw_bytes = cells * 45
    if shutil.disk_usage(args.workdir).free < raw_bytes * 3.2 + 1024**3:
        raise SystemExit("Insufficient disk for real inputs and worst-case output publication")
    directory = Path(tempfile.mkdtemp(prefix="opensubsurface-large-", dir=args.workdir))
    service = None
    evidence = dict(
        format=FORMAT,
        synthetic=True,
        sparse=False,
        shape=args.shape,
        cells=cells,
        runtime=fingerprint(),
        rss_method="20ms polling: parent + all child process RSS; shared pages counted repeatedly",
        physical_io_counters="Not available portably; sizes below are logical file I/O, not physical device traffic",
        data_retained=args.keep_data,
        started_at=datetime.now(timezone.utc).isoformat(),
        host=dict(
            system=__import__("platform").system(),
            machine=__import__("platform").machine(),
            ram_bytes=psutil.virtual_memory().total,
            logical_cpus=psutil.cpu_count(),
        ),
        scope="Raw model is the sum of seven real NPY files, not a single >15GiB file; synthetic Cartesian CPU control",
        phases={},
    )
    try:
        source_folder = directory / "input"
        source_folder.mkdir()
        with Measurement(directory) as measured:
            manifest, grid = generate(source_folder, args.shape, args.block_cells)
        evidence["phases"]["generate_inputs"] = measured.result
        evidence["input_npy_bytes"] = sum(p.stat().st_size for p in source_folder.glob("*.npy"))
        evidence["input_allocated_bytes"] = sum(p.stat().st_blocks * 512 for p in source_folder.glob("*.npy"))
        service = Service(directory / "state")
        pid = service.invoke(
            "project_create", dict(name="Synthetic >15GiB control", vertical_datum="SYNTHETIC")
        )["id"]
        source = LocalSources(service.store).register("Synthetic large", source_folder)
        print("Starting full import and property QC", flush=True)
        with Measurement(directory) as measured:
            props = service.wait(
                service.invoke(
                    "grid_import",
                    dict(
                        project_id=pid,
                        source_id=source["id"],
                        path=manifest.name,
                        file_revision=path_revision(manifest),
                        block_cells=args.block_cells,
                    ),
                ),
                timeout=3600,
            )
        evidence["phases"]["import_and_full_property_qc"] = measured.result
        print("Import and QC completed", flush=True)
        evidence["snapshot_zip_bytes"] = service.store.path(props, "grid.zip").stat().st_size
        evidence["input_sha256"] = props["summary"]["source_sha256"]
        contact = -args.shape[2] / 2 - 0.5
        print("Starting volumetrics", flush=True)
        with Measurement(directory) as measured:
            volume = service.wait(
                service.invoke(
                    "volumetrics_calculate",
                    dict(project_id=pid, properties=ref(props), zone_ids=[1], contact_z_m=contact, bo=1.2),
                ),
                timeout=3600,
            )
        evidence["phases"]["volumetrics"] = measured.result
        print("Starting independent volume and property validation", flush=True)
        with Measurement(directory) as measured:
            validation = service.wait(
                service.invoke("result_validate", dict(project_id=pid, artifact=ref(volume))), timeout=3600
            )
            property_validation = service.wait(
                service.invoke("result_validate", dict(project_id=pid, artifact=ref(props))), timeout=3600
            )
        evidence["phases"]["independent_volume_and_property_validation"] = measured.result
        oil = args.shape[0] * args.shape[1] * min(args.shape[2], -contact)
        expected = dict(
            GRV=cells,
            GRV_oil_interval=oil,
            NetRockVolume=oil * 0.8,
            PV=oil * 0.8 * 0.2,
            HCPV=oil * 0.8 * 0.2 * 0.75,
            STOIIP=oil * 0.8 * 0.2 * 0.75 / 1.2,
        )
        actual = volume["summary"]["values"]
        evidence.update(
            contact_z_m=contact,
            expected=expected,
            actual=actual,
            numerical_validation=validation["summary"]["status"],
            property_validation=property_validation["summary"]["status"],
            working_block_bytes_estimate=props["summary"]["working_memory_bound_bytes"],
            grid=grid,
            max_process_tree_rss_bytes=max(
                p["peak_process_tree_rss_bytes"] for p in evidence["phases"].values()
            ),
        )
        evidence["analytical_control"] = (
            "PASS"
            if all(math.isclose(actual[k], v, rel_tol=1e-8, abs_tol=1e-7) for k, v in expected.items())
            else "FAIL"
        )
        evidence["memory_control"] = (
            "PASS" if evidence["max_process_tree_rss_bytes"] <= args.max_rss_mib * 1024**2 else "FAIL"
        )
        evidence["size_control"] = (
            "PASS" if evidence["input_npy_bytes"] > 15 * 1024**3 else "SMALL_CONTROL_ONLY"
        )
        evidence["non_sparse_input_control"] = (
            "PASS" if evidence["input_allocated_bytes"] >= evidence["input_npy_bytes"] else "FAIL"
        )
        evidence["sampled_workspace_allocated_peak_bytes"] = max(
            p["sampled_workspace_allocated_peak_bytes"] for p in evidence["phases"].values()
        )
        evidence["disk_budget_control"] = (
            "PASS" if evidence["sampled_workspace_allocated_peak_bytes"] <= 60 * 1024**3 else "FAIL"
        )
        evidence["overall"] = (
            "PASS"
            if all(
                evidence[k] == "PASS"
                for k in (
                    "analytical_control",
                    "memory_control",
                    "numerical_validation",
                    "property_validation",
                    "non_sparse_input_control",
                    "disk_budget_control",
                )
            )
            else "FAIL"
        )
        if args.keep_data:
            evidence["directory"] = str(directory)
    finally:
        try:
            if service:
                service.close()
        finally:
            if not args.keep_data:
                shutil.rmtree(directory)
            evidence["temporary_data_removed"] = not directory.exists()
            evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2), flush=True)
    if evidence.get("overall") != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shape", nargs=3, type=int, default=[1024, 1024, 384])
    parser.add_argument("--block-cells", type=int, default=262144)
    parser.add_argument("--output", type=Path, default=Path("docs/benchmark-large.json"))
    parser.add_argument("--workdir", type=Path, default=Path(tempfile.gettempdir()))
    parser.add_argument("--max-rss-mib", type=int, default=1024)
    parser.add_argument("--keep-data", action="store_true")
    run(parser.parse_args())
