import json
import zipfile

import numpy as np
import pytest
import xtgeo

from opensubsurface.adapters.cornerpoint import FORMAT, cell_volumes, clipped_tetra, tetra_volume
from opensubsurface.adapters.large_grid import UNITS, evaluate
from opensubsurface.adapters.local_sources import LocalSources, path_revision
from opensubsurface.calculations.cornerpoint_reference import integral
from opensubsurface.errors import DomainError


def ref(obj):
    return dict(id=obj["id"], revision=obj["revision"])


def source(service, tmp_path, fmt):
    folder = tmp_path / "source"
    folder.mkdir()
    grid = xtgeo.create_box_grid((3, 4, 2), origin=(100, 200, 1000), increment=(10, 20, 5), rotation=27)
    active = np.ones(grid.dimensions, np.int32)
    active[1, 2, 1] = 0
    grid.set_actnum(xtgeo.GridProperty(ncol=3, nrow=4, nlay=2, values=active, discrete=True))
    path = folder / ("grid." + fmt)
    grid.to_file(path, fformat=fmt)
    constants = dict(zones=1, phi=0.2, ntg=0.8, sw=0.25, permeability_md=100, kz_ratio=0.1)
    manifest = dict(
        format=FORMAT,
        shape=list(grid.dimensions),
        geometry=dict(path=path.name, file_revision=path_revision(path), format=fmt),
        crs="LOCAL_METRIC",
        vertical_datum="TEST",
        length_unit="m",
        z_direction="down",
        units=UNITS,
        arrays={k: dict(constant=v) for k, v in constants.items()},
        assumptions=["Rotated analytic box; explicit scalar properties"],
    )
    path = folder / "model.json"
    path.write_text(json.dumps(manifest))
    src = LocalSources(service.store).register("cornerpoint", folder)
    pid = service.invoke("project_create", dict(name="Corner point", vertical_datum="TEST"))["id"]
    return dict(
        project_id=pid, source_id=src["id"], path=path.name, file_revision=path_revision(path)
    ), folder


@pytest.mark.parametrize("fmt", ["grdecl", "egrid", "roff"])
def test_real_native_formats_active_rotated_geometry_contacts_and_report(service, tmp_path, fmt):
    args, _ = source(service, tmp_path, fmt)
    props = service.wait(service.invoke("grid_import", args))
    assert props["summary"]["active_cells"] == 23
    obj = dict(props, paths={"grid.zip": str(service.store.path(props, "grid.zip"))})
    cases = [dict(zone_ids=[1], contact_z_m=z, bo=1.2) for z in (-1015, -1007.5, -995)]
    results = evaluate(obj, cases)
    assert results[0]["GRV"] == pytest.approx(23000)
    # Twelve top cells completely oil-filled, eleven bottom cells half oil-filled.
    assert results[1]["GRV_oil_interval"] == pytest.approx(17500)
    assert results[1]["STOIIP"] == pytest.approx(1750)
    assert results[2]["STOIIP"] == 0
    validation = service.wait(
        service.invoke("result_validate", dict(project_id=args["project_id"], artifact=ref(props)))
    )
    assert validation["summary"]["status"] == "PASS"
    LocalSources(service.store).remove(args["source_id"])
    plan = service.invoke(
        "calculation_plan",
        dict(
            project_id=args["project_id"],
            properties=ref(props),
            zone_ids=[1],
            bo=1.2,
            contacts=[dict(name="OWC", z_m=-1007.5)],
            assumptions=["Analytical control"],
        ),
    )
    run = service.invoke("calculation_run", dict(project_id=args["project_id"], plan=ref(plan)))
    service.wait(run)
    status = service.invoke("calculation_status", dict(project_id=args["project_id"], run_id=run["run_id"]))
    report = service.store.object(args["project_id"], status["report"])
    assert report["summary"]["validation_status"] == "PASS"


def test_warped_repeated_depth_and_partial_tetrahedra_against_independent_hull():
    rng = np.random.default_rng(44)
    corners = np.array(
        [[0, 0, 0], [2, 0, 0], [0, 3, 0], [2, 3, 0], [0, 0, 4], [2, 0, 4], [0, 3, 4], [2, 3, 4]], float
    )
    cells = np.tile(corners, (50, 1, 1))
    cells[1:] += rng.normal(0, 0.15, cells[1:].shape)
    for contact in (-1, 0, 0.7, 2, 4, 5):
        assert cell_volumes(cells, contact) == pytest.approx(integral(cells, contact), rel=1e-10, abs=1e-10)
    tetra = rng.normal(size=(1000, 4, 3))
    clipped = clipped_tetra(tetra, 0)
    assert np.all(clipped >= -1e-12)
    assert np.all(clipped <= tetra_volume(tetra) + 1e-12)


def test_missing_geometry_chunk_and_include_cannot_pass(service, tmp_path):
    args, folder = source(service, tmp_path, "grdecl")
    geometry = folder / "grid.grdecl"
    geometry.write_text(geometry.read_text() + "\nINCLUDE\n'/etc/passwd' /\n")
    manifest = json.loads((folder / "model.json").read_text())
    manifest["geometry"]["file_revision"] = path_revision(geometry)
    (folder / "model.json").write_text(json.dumps(manifest))
    args["file_revision"] = path_revision((folder / "model.json"))
    with pytest.raises(DomainError, match="INCLUDE"):
        service.wait(service.invoke("grid_import", args))
    geometry.write_text(geometry.read_text().split("\nINCLUDE")[0])
    manifest["geometry"]["file_revision"] = path_revision(geometry)
    (folder / "model.json").write_text(json.dumps(manifest))
    args["file_revision"] = path_revision((folder / "model.json"))
    props = service.wait(service.invoke("grid_import", args))
    damaged = tmp_path / "broken.zip"
    with zipfile.ZipFile(service.store.path(props, "grid.zip")) as old, zipfile.ZipFile(damaged, "w") as new:
        for name in old.namelist():
            if name != "corners/0.0.0":
                new.writestr(name, old.read(name))
    bad = service.store.publish(args["project_id"], "properties", props["summary"], {"grid.zip": damaged})
    check = service.wait(
        service.invoke("result_validate", dict(project_id=args["project_id"], artifact=ref(bad)))
    )
    assert check["summary"]["status"] == "FAIL"


def test_egrid_refinement_cannot_be_silently_dropped(service, tmp_path):
    args, folder = source(service, tmp_path, "egrid")
    path = folder / "grid.egrid"
    with path.open("ab") as stream:
        stream.write(b"\x00\x00\x00\x10LGR     " + b"\x00\x00\x00\x01CHAR\x00\x00\x00\x10")
    manifest = json.loads((folder / "model.json").read_text())
    manifest["geometry"]["file_revision"] = path_revision(path)
    (folder / "model.json").write_text(json.dumps(manifest))
    args["file_revision"] = path_revision((folder / "model.json"))
    with pytest.raises(DomainError, match="LGR"):
        service.wait(service.invoke("grid_import", args))
