import json

import numpy as np
import pytest
import zarr

from opensubsurface.adapters.eclipse_deck import Interpreter
from opensubsurface.adapters.eclipse_import import import_deck, reconstruct
from opensubsurface.adapters.local_sources import LocalSources, revision
from opensubsurface.errors import DomainError


def fixture_deck(tmp_path, service):
    root = tmp_path / "source"
    root.mkdir()
    sub = root / "sub"
    sub.mkdir()
    coord = []
    for j in range(4):
        for i in range(3):
            coord.extend([i * 10, j * 20, 100, i * 10, j * 20, 120])
    z = np.repeat([100, 110, 110, 120], 24)
    (sub / "geometry.inc").write_text(
        "COORD\n" + " ".join(map(str, coord)) + " /\nZCORN\n" + " ".join(map(str, z)) + " /\n"
    )
    path = root / "MODEL.DATA"
    path.write_text("""RUNSPEC
DIMENS
2 3 2 /
METRIC
GRID
INCLUDE
'./sub/geometry.inc' /
ACTNUM
12*1 /
PORO
12*0.2 /
NTG
12*0.8 /
PERMX
12*100 /
COPY
 PERMX PERMZ /
/
MULTIPLY
 PERMZ 0.1 /
/
BOX
2 2 2 3 1 1 /
PORO
2*0.3 /
ENDBOX
EDIT
ADD
 PORO 0.1 1 1 1 1 2 2 /
/
PROPS
SWAT
12*0.25 /
REGIONS
FIPNUM
6*1 6*2 /
EQUALS
 SATNUM 2 /
 EQLNUM 3 /
/
GRID
MINPV
500 /
END
""")
    source = LocalSources(service.store).register("test", root)
    return path, source


def test_static_edits_boxes_geometry_and_unknowns(service, tmp_path):
    path, source = fixture_deck(tmp_path, service)
    out = tmp_path / "parsed"
    out.mkdir()
    deck = Interpreter(source, path.name, out).parse()
    expected = np.full((2, 3, 2), 0.2)
    expected[1, 1:3, 0] = 0.3
    expected[0, 0, 1] += 0.1
    np.testing.assert_allclose(deck.arrays["PORO"], expected.ravel(order="F"))
    assert np.all(deck.arrays["PERMZ"] == 10)
    assert np.all(deck.arrays["EQLNUM"] == 3)
    assert any(item["keyword"] == "MINPV" and item["line"] > 0 for item in deck.unsupported)
    corners = reconstruct(deck.arrays["COORD"], deck.arrays["ZCORN"], deck.shape, 0, 12, 1, "down")
    np.testing.assert_allclose(
        corners[0],
        [
            [0, 0, -100],
            [10, 0, -100],
            [0, 20, -100],
            [10, 20, -100],
            [0, 0, -110],
            [10, 0, -110],
            [0, 20, -110],
            [10, 20, -110],
        ],
    )
    np.testing.assert_allclose(corners[-1].mean(axis=0), [15, 50, -115])
    # Independent native reader of the same source geometry.
    import xtgeo

    native = root = tmp_path / "native.grdecl"
    native.write_text("SPECGRID\n2 3 2 1 F /\n" + (path.parent / "sub/geometry.inc").read_text())
    grid = xtgeo.grid_from_file(root, fformat="grdecl")
    expected = np.stack([v.values.ravel(order="F") for v in grid.get_xyz_corners()], axis=1).reshape(-1, 8, 3)
    expected[:, :, 2] *= -1
    np.testing.assert_allclose(corners, expected)


def test_import_preserves_regions_and_reports_unsupported(service, tmp_path):
    path, source = fixture_deck(tmp_path, service)
    out = tmp_path / "output"
    out.mkdir()
    p = dict(
        path=path.name,
        file_revision=revision(path.stat()),
        length_unit="m",
        z_direction="down",
        defaults={},
        region_field="FIPNUM",
        crs="EPSG:32632",
        vertical_datum="TEST",
        assumptions=["Test fixture"],
        block_cells=1024,
    )
    kind, summary, files = import_deck(dict(source=source), p, out)
    assert kind == "properties" and summary["active_cells"] == 12
    with zarr.ZipStore(str(files["grid.zip"]), mode="r") as store:
        g = zarr.open_group(store=store)
        assert np.all(g["SATNUM"][:] == 2) and np.all(g["EQLNUM"][:] == 3)
        assert np.all(g["kz_ratio"][:] == 0.1)
    report = json.loads(files["import_report.json"].read_text())
    assert report["status"] == "PASS" and "MINPV" in {v["keyword"] for v in report["unsupported_keywords"]}
    assert {v["status"] for v in report["checks"]} == {"PASS", "NOT RUN"}


@pytest.mark.parametrize("include", ["../escape.inc", "/tmp/escape.inc", "cycle.DATA", "link.inc"])
def test_include_escape_cycle_symlink_rejected(service, tmp_path, include):
    root = tmp_path / "input"
    root.mkdir()
    outside = tmp_path / "escape.inc"
    outside.write_text("PORO\n1*0.2 /\n")
    (root / "link.inc").symlink_to(outside)
    path = root / "cycle.DATA"
    path.write_text("INCLUDE\n'" + include + "' /\n")
    source = LocalSources(service.store).register("guard", root)
    with pytest.raises(DomainError):
        Interpreter(source, path.name, tmp_path).parse()


def test_include_parent_inside_source_is_allowed(service, tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    (root / "sub").mkdir()
    (root / "root.inc").write_text("DIMENS\n1 1 1 /\n")
    (root / "sub/model.DATA").write_text("INCLUDE\n'../root.inc' /\n")
    source = LocalSources(service.store).register("relative", root)
    assert Interpreter(source, "sub/model.DATA", tmp_path).parse().shape == (1, 1, 1)


def test_tall_box_selection_is_constant_memory_and_unit_modes_fail_closed(service, tmp_path):
    from opensubsurface.adapters.eclipse_deck import BoxSlices

    selections = BoxSlices((1, 1, 20_000_000), (1, 1, 1, 1, 1, 20_000_000))
    assert len(selections) == 20_000_000 and selections.cells == 20_000_000
    assert selections[0] == slice(0, 1) and selections[19_999_999] == slice(19_999_999, 20_000_000)
    path, source = fixture_deck(tmp_path, service)
    path.write_text(path.read_text().replace("GRID\nINCLUDE", "GRID\nMAPUNITS\n'FEET' /\nINCLUDE", 1))
    output = tmp_path / "units-output"
    output.mkdir()
    with pytest.raises(DomainError, match="Mixed GRIDUNIT/MAPUNITS"):
        import_deck(
            dict(source=source),
            dict(
                path=path.name,
                file_revision=revision(path.stat()),
                length_unit="m",
                z_direction="down",
                defaults={},
                region_field="FIPNUM",
                crs="LOCAL_METRIC",
                vertical_datum="TEST",
                assumptions=["Synthetic unit conflict"],
                block_cells=1024,
            ),
            output,
        )
