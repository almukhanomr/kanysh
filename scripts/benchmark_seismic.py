"""Actual >256 MiB SEG-Y → owner-source job → float32 Zarr, with every sample compared.

Synthetic poststack acceptance, not field seismic. Temporary data are removed even on failure.
"""

import argparse
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import segyio
from benchmark_large import Measurement

from opensubsurface.adapters.local_sources import LocalSources, revision
from opensubsurface.adapters.seismic import open_volume
from opensubsurface.execution.provenance import fingerprint
from opensubsurface.service import Service


def run(output):
    directory = Path(tempfile.mkdtemp(prefix="opensubsurface-segy-"))
    evidence = dict(
        synthetic=True,
        started_at=datetime.now(timezone.utc).isoformat(),
        shape=[64, 64, 16384],
        runtime=fingerprint(),
        phases={},
        scope="One actual SEG-Y >256 MiB, all 67,108,864 float32 samples; no downsampling",
        rss_method="20ms sampled process-tree RSS, excludes OS file cache and can miss short peaks",
    )
    service = None
    try:
        folder = directory / "input"
        folder.mkdir()
        source = folder / "control.segy"
        spec = segyio.spec()
        spec.samples, spec.format, spec.tracecount = np.arange(16384) * 4, 5, 4096
        rng = np.random.default_rng(44)
        with Measurement(directory) as measured:
            with segyio.create(str(source), spec) as f:
                f.bin[segyio.BinField.Interval] = 4000
                f.bin[segyio.BinField.MeasurementSystem] = 1
                for n in range(4096):
                    i, j = divmod(n, 64)
                    f.header[n] = {
                        189: 100 + i,
                        193: 200 + j,
                        segyio.TraceField.TRACE_SAMPLE_COUNT: 16384,
                        segyio.TraceField.TRACE_SAMPLE_INTERVAL: 4000,
                        segyio.TraceField.CoordinateUnits: 1,
                        segyio.TraceField.CDP_X: 400000 + i * 25,
                        segyio.TraceField.CDP_Y: 7000000 + j * 25,
                    }
                    f.trace[n] = rng.standard_normal(16384).astype(np.float32)
        evidence["phases"]["generate"] = measured.result
        evidence["source_bytes"] = source.stat().st_size
        service = Service(directory / "state")
        pid = service.invoke("project_create", dict(name="Large SEG-Y control", vertical_datum="TEST"))["id"]
        registered = LocalSources(service.store).register("Synthetic SEG-Y", folder)
        with Measurement(directory) as measured:
            obj = service.wait(
                service.invoke(
                    "seismic_source_import",
                    dict(
                        project_id=pid,
                        source_id=registered["id"],
                        path=source.name,
                        file_revision=revision(source.stat()),
                        crs="LOCAL_METRIC",
                        vertical_datum="TEST",
                        domain="twt",
                        sample_unit="ms",
                    ),
                )
            )
        evidence["phases"]["import"] = measured.result
        snapshot = service.store.path(obj, "cube.zip")
        evidence["snapshot_bytes"], evidence["summary"] = snapshot.stat().st_size, obj["summary"]
        with Measurement(directory) as measured:
            store, g = open_volume(snapshot)
            try:
                with segyio.open(str(source), "r", ignore_geometry=True) as f:
                    for n in range(f.tracecount):
                        i, j = divmod(n, 64)
                        if not np.array_equal(g["amplitude"][i, j, :], np.asarray(f.trace[n])):
                            raise AssertionError("Amplitude mismatch at trace " + str(n))
                        assert g["x"][i, j] == 400000 + i * 25 and g["y"][i, j] == 7000000 + j * 25
                assert np.array_equal(g["inline"][:], np.arange(100, 164))
                assert np.array_equal(g["crossline"][:], np.arange(200, 264))
                assert np.allclose(g["sample"][:], np.arange(16384) * 0.004, rtol=0, atol=1e-12)
            finally:
                store.close()
        evidence["phases"]["independent_all_trace_comparison"] = measured.result
        evidence["all_sample_comparison"] = "bitwise exact for all 67,108,864 source IEEE float32 samples"
        evidence["status"] = (
            "PASS"
            if (
                evidence["source_bytes"] > 256 * 1024**2
                and max(p["peak_process_tree_rss_bytes"] for p in evidence["phases"].values()) < 1024**3
            )
            else "FAIL"
        )
    finally:
        if service:
            service.close()
        shutil.rmtree(directory)
        evidence["temporary_data_removed"] = not directory.exists()
        output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2), flush=True)
    if evidence["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/benchmark-seismic.json"))
    run(parser.parse_args().output)
