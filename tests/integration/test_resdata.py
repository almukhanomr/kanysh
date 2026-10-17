"""Native resdata I/O fixture, not evidence of an OPM solve."""

from datetime import datetime

import numpy as np
import pytest

from opensubsurface.adapters.opm import read_summary
from opensubsurface.adapters.results import read_restart_fields, snapshot
from opensubsurface.errors import DomainError

resdata = pytest.importorskip("resdata", reason="Optional solver extra not installed")


def test_native_summary_reader_with_explicit_standard_conditions(tmp_path):
    from resdata.summary import Summary

    writer = Summary.writer(str(tmp_path / "CASE"), datetime(2026, 1, 1), 3, 4, 2)
    for name, unit in [("FOPT", "SM3"), ("FOPR", "SM3/DAY"), ("FWPR", "SM3/DAY"), ("FPR", "BARSA")]:
        writer.add_variable(name, unit=unit)
    for i, day in enumerate([0, 1, 2]):
        step = writer.add_t_step(i + 1, day)
        step["FOPT"] = float(day * 10)
        step["FOPR"] = 10.0
        step["FWPR"] = 0.0
        step["FPR"] = 200.0 - day
    writer.fwrite()
    parsed = read_summary(tmp_path / "CASE.SMSPEC", dict(pressure_pa=101325.0, temperature_k=288.71))
    assert parsed["vectors"]["FOPT"]["values"] == [0, 10, 20]
    assert parsed["vectors"]["FPR"]["unit"] == "bara"
    assert parsed["elapsed_days"] == [0, 1, 2]
    assert parsed["dates"][0] == "2026-01-01T00:00:00+00:00"
    assert parsed["provenance"].startswith("OPM/Eclipse summary read by resdata")


def test_snapshot_asymmetric_axis_and_report_mapping(tmp_path):
    import zarr

    path = tmp_path / "states.zip"
    values = np.arange(48).reshape(2, 3, 4, 2).astype(float)
    with zarr.ZipStore(str(path), mode="w") as store:
        group = zarr.group(store=store)
        group.create_dataset("pressure", data=values)
        group.attrs.update(
            dates=["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"], units=dict(pressure="bara")
        )
    section, metadata = snapshot(path, 1, "pressure", "XZ", 2)
    np.testing.assert_array_equal(section, values[1, :, 2, :])
    assert metadata["date"] == "2026-01-02T00:00:00+00:00" and metadata["shape"] == [3, 2]


def test_native_restart_reader_with_inactive_cells_and_two_reports(tmp_path):
    """Independent resfo writer creates a minimal format fixture; no solver ran."""
    import resfo
    import zarr
    from resdata.grid import GridGenerator

    shape = (3, 4, 2)
    active = np.ones(shape, dtype=bool)
    active[1, 2, 0] = False
    # Explicit I-fast/K-down sequence, independent of production to_opm/from_opm functions.
    indices = [(i, j, k) for k in [1, 0] for j in range(4) for i in range(3)]
    actnum = [int(active[ijk]) for ijk in indices]
    grid = GridGenerator.create_rectangular(shape, (10, 20, 5), actnum=actnum)
    grid.save_EGRID(str(tmp_path / "CASE.EGRID"))
    np.savez(tmp_path / "mapping.npz", active=active)
    pv = np.arange(24, dtype=np.float32) + 100
    resfo.write(tmp_path / "CASE.INIT", [("PORV    ", pv)])
    keywords = []
    for report in [0, 1]:
        integer = np.zeros(411, dtype=np.int32)
        integer[2] = 1  # METRIC unit convention
        integer[8:12] = [*shape, sum(actnum)]
        integer[14] = 3  # Oil and water
        integer[64:67] = [1 + report, 1, 2026]
        integer[94] = 100  # Eclipse 100 compatible format
        double = np.zeros(229, dtype=np.float64)
        double[0] = report
        selected = np.flatnonzero(actnum)
        keywords.extend(
            [
                ("SEQNUM  ", np.array([report + 1], dtype=np.int32)),
                ("INTEHEAD", integer),
                ("LOGIHEAD", np.zeros(100, dtype=bool)),
                ("DOUBHEAD", double),
                ("PRESSURE", (200 + 10 * report + selected / 100).astype(np.float32)),
                ("SWAT    ", (0.2 + selected / 1000).astype(np.float32)),
            ]
        )
    resfo.write(tmp_path / "CASE.UNRST", keywords)
    output = tmp_path / "states.zip"
    metadata = read_restart_fields(tmp_path, tmp_path / "mapping.npz", output)
    assert metadata["restart_days"] == [0, 1] and metadata["restart_reports"] == [1, 2]
    assert metadata["restart_dates"][-1] == "2026-01-02T00:00:00+00:00"
    with zarr.ZipStore(str(output), mode="r") as store:
        data = zarr.open_group(store)
        for flat, ijk in enumerate(indices):
            if active[ijk]:
                assert data["pore_volume"][ijk] == pv[flat]
                for report in [0, 1]:
                    assert data["pressure"][(report, *ijk)] == pytest.approx(200 + 10 * report + flat / 100)
                    assert data["sw"][(report, *ijk)] == pytest.approx(0.2 + flat / 1000)
                    assert data["so"][(report, *ijk)] == pytest.approx(0.8 - flat / 1000)
            else:
                assert np.isnan(data["pressure"][(0, *ijk)])
    np.savez(tmp_path / "wrong-mapping.npz", active=np.ones(shape, dtype=bool))
    with pytest.raises(DomainError, match="ACTNUM"):
        read_restart_fields(tmp_path, tmp_path / "wrong-mapping.npz", tmp_path / "invalid.zip")
