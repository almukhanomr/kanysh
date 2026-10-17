import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import xtgeo

from opensubsurface.adapters.geodata import import_geodata
from opensubsurface.adapters.local_sources import LocalSources, path_revision


def run(service, tmp_path, path, kind, fmt, resolved=None, **kw):
    source = LocalSources(service.store).register("interchange", path.parent)
    out = tmp_path / ("out-" + str(len(list(tmp_path.iterdir()))))
    out.mkdir()
    p = dict(
        path=path.name,
        file_revision=path_revision(path),
        kind=kind,
        format=fmt,
        name="H1",
        well_id="A-1",
        md_column="MD",
        length_unit="m",
        z_direction="down",
        columns={},
        column_indices={},
        skiprows=0,
        delimiter=None,
        cps_order=None,
        cps_y_first=None,
        assumptions=["Synthetic interchange test"],
        crs="LOCAL_METRIC",
        vertical_datum="TEST",
    )
    p.update(kw)
    result = import_geodata(dict(source=source), p, resolved or {}, out)
    return result, pq.read_table(out / "data.parquet").to_pandas()


@pytest.mark.parametrize("fmt", ["irap_ascii", "irap_binary", "zmap_ascii"])
def test_surface_nodes_mask_orientation_and_units(service, tmp_path, fmt):
    a = np.ma.array([[100, 110, 120], [200, 210, 220]], mask=[[False, False, False], [False, True, False]])
    surface = xtgeo.RegularSurface(2, 3, xori=1000, yori=2000, xinc=10, yinc=20, values=a)
    path = tmp_path / ("surface." + fmt)
    surface.to_file(path, fformat=fmt)
    result, table = run(service, tmp_path, path, "surfaces", fmt)
    assert result[0] == "dataset" and len(table) == 5
    expected = {
        (1000.0, 2000.0): -100.0,
        (1000.0, 2020.0): -110.0,
        (1000.0, 2040.0): -120.0,
        (1010.0, 2000.0): -200.0,
        (1010.0, 2040.0): -220.0,
    }
    assert {(r.x, r.y): r.z for r in table.itertuples()} == expected


def test_cps3_explicit_column_direction(service, tmp_path):
    path = tmp_path / "surface.cps3"
    path.write_text(
        'FSASCI 0 1 "Computed" 0 1e30\nFSATTR 0 0\nFSLIMI 10 20 30 70 0 999\nFSNROW 3 2\nFSXINC 10 20\n->Synthetic\n1 4 2 1e30 3 6\n'
    )
    _, t = run(service, tmp_path, path, "surfaces", "cps3_ascii", cps_order="row_major", cps_y_first="max")
    assert {(round(r.x, 9), round(r.y, 9)): r.z for r in t.itertuples()} == {
        (10.0, 30.0): -3.0,
        (10.0, 50.0): -2.0,
        (10.0, 70.0): -1.0,
        (20.0, 30.0): -6.0,
        (20.0, 70.0): -4.0,
    }


def test_rms_well_native_md_and_coordinates(service, tmp_path):
    df = pd.DataFrame(
        dict(
            X_UTME=[10.0, 11.0, 12.0],
            Y_UTMN=[20.0, 21.0, 22.0],
            Z_TVDSS=[100.0, 110.0, 120.0],
            MD=[0.0, 11.0, 23.0],
        )
    )
    well = xtgeo.Well(wname="A-1", df=df, mdlogname="MD")
    path = tmp_path / "A-1.w"
    well.to_file(path, fformat="rms_ascii")
    _, t = run(service, tmp_path, path, "trajectory", "rms_ascii")
    np.testing.assert_allclose(
        t[["x", "y", "z", "md"]], [[10, 20, -100, 0], [11, 21, -110, 11], [12, 22, -120, 23]]
    )


def test_petrel_ascii_mapped_quoted_well_tops_and_poly(service, tmp_path):
    path = tmp_path / "track.txt"
    path.write_text('Export header\n"A 1" 0 10 20 100\n"A 1" 100 30 40 200\n')
    _, t = run(
        service,
        tmp_path,
        path,
        "trajectory",
        "petrel_ascii",
        skiprows=1,
        column_indices=dict(well_id=0, md=1, x=2, y=3, z=4),
    )
    assert t.well_id.tolist() == ["A 1", "A 1"]
    trajectory = tmp_path / "track.parquet"
    pq.write_table(pa.Table.from_pandas(t, preserve_index=False), trajectory)
    marker = tmp_path / "tops.txt"
    marker.write_text('"A 1" "Top sand" 50\n')
    _, t = run(
        service,
        tmp_path,
        marker,
        "markers",
        "petrel_ascii",
        resolved=dict(trajectory=dict(paths={"data.parquet": str(trajectory)})),
        column_indices=dict(well_id=0, horizon=1, md=2),
    )
    np.testing.assert_allclose(t[["x", "y", "z"]], [[20, 30, -150]])
    poly = tmp_path / "poly.xyz"
    poly.write_text("0 0 0\n10 0 0\n10 10 0\n0 0 0\n")
    _, t = run(service, tmp_path, poly, "polygons", "xyz")
    assert len(t) == 4 and t.polygon_id.nunique() == 1
