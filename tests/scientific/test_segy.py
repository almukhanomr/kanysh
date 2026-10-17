import numpy as np
import pytest
import segyio

from opensubsurface.adapters.seismic import import_segy, open_volume
from opensubsurface.schemas import SeismicImport


def write_segy(path, endian):
    spec = segyio.spec()
    spec.sorting = 2
    spec.format = 5
    spec.samples = np.arange(16) * 4.0
    spec.ilines = [10, 11]
    spec.xlines = [20, 21, 22]
    spec.endian = endian
    with segyio.create(str(path), spec) as f:
        for n in range(6):
            i, j = divmod(n, 3)
            f.header[n] = {
                segyio.TraceField.INLINE_3D: 10 + i,
                segyio.TraceField.CROSSLINE_3D: 20 + j,
                segyio.TraceField.CDP_X: i * 2500,
                segyio.TraceField.CDP_Y: j * 2500,
                segyio.TraceField.SourceGroupScalar: -100,
                segyio.TraceField.CoordinateUnits: 1,
                segyio.TraceField.TRACE_SAMPLE_COUNT: 16,
                segyio.TraceField.TRACE_SAMPLE_INTERVAL: 4000,
            }
            f.trace[n] = np.full(16, n + 1, np.float32)
        f.bin[segyio.BinField.Interval] = 4000


@pytest.mark.parametrize("endian", ["big", "little"])
def test_header_scalar_endian_streaming(tmp_path, endian):
    source = tmp_path / "source.segy"
    write_segy(source, endian)
    out = tmp_path / "out"
    out.mkdir()
    p = SeismicImport(
        project_id="test",
        upload_id="u",
        crs="LOCAL_METRIC",
        vertical_datum="SYNTHETIC",
        domain="twt",
        sample_unit="ms",
        endian=endian,
    ).model_dump(mode="json")
    _, summary, files = import_segy(source, p, out)
    store, group = open_volume(files["cube.zip"])
    try:
        assert summary["shape"] == [2, 3, 16]
        assert group["x"][1, 0] == 25
        assert group["y"][0, 2] == 50
        np.testing.assert_allclose(group["sample"][:], np.arange(16) * 0.004)
        np.testing.assert_allclose(group["amplitude"][1, 2, :], 6)
    finally:
        store.close()
