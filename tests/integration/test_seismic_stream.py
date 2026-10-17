import numpy as np
import pytest
import segyio

from opensubsurface.adapters.local_sources import LocalSources, revision
from opensubsurface.adapters.seismic import open_volume, read_section
from opensubsurface.adapters.seismic_stream import convert
from opensubsurface.errors import DomainError


def segy_file(path, order="inline", missing=False, unsorted=False, ns=32, ni=3, nj=4):
    cells = [(i, j) for i in range(ni) for j in range(nj)]
    if order == "crossline":
        cells.sort(key=lambda c: c[::-1])
    if missing:
        cells.remove((1, 2))
    if unsorted:
        cells[2], cells[3] = cells[3], cells[2]
    spec = segyio.spec()
    spec.samples, spec.format, spec.tracecount = np.arange(ns) * 4, 5, len(cells)
    with segyio.create(str(path), spec) as f:
        f.bin[segyio.BinField.Interval] = 4000
        f.bin[segyio.BinField.MeasurementSystem] = 1
        for n, (i, j) in enumerate(cells):
            f.header[n] = {
                189: 100 + i * 2,
                193: 200 + j * 3,
                segyio.TraceField.TRACE_SAMPLE_COUNT: ns,
                segyio.TraceField.TRACE_SAMPLE_INTERVAL: 4000,
                segyio.TraceField.CoordinateUnits: 1,
                segyio.TraceField.SourceGroupScalar: -10,
                segyio.TraceField.CDP_X: 1000 + i * 250,
                segyio.TraceField.CDP_Y: 2000 + j * 250,
            }
            f.trace[n] = (np.arange(ns) * 0.25 + 100 * i + 10 * j).astype(np.float32)


def params():
    return dict(
        crs="LOCAL_METRIC",
        vertical_datum="TEST",
        domain="twt",
        sample_unit="ms",
        coordinate_unit="m",
        endian="big",
        inline_byte=189,
        crossline_byte=193,
    )


@pytest.mark.parametrize("order", ["inline", "crossline"])
def test_both_source_orders_exact_amplitudes_geometry_and_missing_mask(tmp_path, order):
    path = tmp_path / "input.segy"
    segy_file(path, order=order, missing=True)
    summary, files = convert(path, params(), tmp_path)
    assert summary["shape"] == [3, 4, 32]
    assert summary["missing_traces"] == 1
    assert summary["source_order"] == order
    store, g = open_volume(files["cube.zip"])
    try:
        assert g["amplitude"].dtype == np.dtype("float32")
        for i in range(3):
            for j in range(4):
                actual = g["amplitude"][i, j]
                if (i, j) == (1, 2):
                    assert np.isnan(actual).all()
                else:
                    assert np.array_equal(actual, np.arange(32, dtype=np.float32) * 0.25 + 100 * i + 10 * j)
                    assert g["x"][i, j] == 100 + 25 * i
                    assert g["y"][i, j] == 200 + 25 * j
        assert g["sample"][:] == pytest.approx(np.arange(32) * 0.004)
    finally:
        store.close()


def test_unordered_units_and_source_revision_fail_closed(service, tmp_path):
    path = tmp_path / "input.segy"
    segy_file(path, unsorted=True)
    with pytest.raises(DomainError, match="sorted"):
        convert(path, params(), tmp_path)
    segy_file(path)
    with pytest.raises(DomainError, match="measurement"):
        convert(path, dict(params(), coordinate_unit="ft"), tmp_path)
    src = LocalSources(service.store).register("SEG-Y", tmp_path)
    pid = service.invoke("project_create", dict(name="SEG-Y", vertical_datum="TEST"))["id"]
    args = dict(
        params(), project_id=pid, source_id=src["id"], path=path.name, file_revision=revision(path.stat())
    )
    volume = service.wait(service.invoke("seismic_source_import", args))
    assert volume["summary"]["storage"] == "seismic-zarr-f32-v1"
    assert len(volume["summary"]["source_sha256"]) == 64
    assert not list((service.store.root / "attempts").rglob("working.segy"))
    path.touch()
    with pytest.raises(DomainError, match="source_scan"):
        service.invoke("seismic_source_import", args)


def test_oversized_slice_is_rejected_before_reading_or_allocating():
    class HeaderOnly:
        shape = (100000, 100000, 2000)

        def __getitem__(self, _):
            raise AssertionError("Must reject before any data access")

    with pytest.raises(DomainError, match="4 млн"):
        read_section({"amplitude": HeaderOnly()}, 0, 0)
