import json
import zipfile

import numpy as np
import pytest

from opensubsurface.adapters.large_grid import FORMAT, UNITS, evaluate
from opensubsurface.adapters.local_sources import LocalSources, revision
from opensubsurface.calculations.validation import reference_volumes
from opensubsurface.domain.numerics import to_opm, volumes
from opensubsurface.errors import DomainError
from opensubsurface.service import ref


def fixture_source(service, tmp_path, arrays=None):
    folder = tmp_path / "cartesian"
    folder.mkdir()
    shape = (13, 17, 19)
    grid = dict(shape=list(shape), extent=[17, 43, -20, 31, -193, -79])
    idx = np.indices(shape)
    active = (idx[0] + idx[1] + idx[2]) % 11 != 0
    if arrays is None:
        arrays = dict(
            active=active,
            zones=(1 + (idx[0] % 2)).astype(np.int32),
            phi=0.1 + idx[2] / 100,
            ntg=0.5 + idx[1] / 50,
            sw=0.2 + idx[0] / 100,
            permeability_md=np.full(shape, 100.0),
            kz_ratio=np.full(shape, 0.1),
        )
        for name in UNITS:
            if name not in ("active", "zones"):
                arrays[name][~active] = np.nan
    manifest = dict(
        format=FORMAT,
        grid=grid,
        crs="LOCAL_METRIC",
        vertical_datum="TEST",
        z_direction="up",
        units=UNITS,
        arrays={},
    )
    for name, data in arrays.items():
        path = folder / (name + ".npy")
        np.save(path, data, allow_pickle=False)
        manifest["arrays"][name] = dict(path=path.name, file_revision=revision(path.stat()))
    path = folder / "model.json"
    path.write_text(json.dumps(manifest))
    source = LocalSources(service.store).register("Cartesian control", folder)
    pid = service.invoke("project_create", dict(name="Large grid", vertical_datum="TEST"))["id"]
    args = dict(
        project_id=pid,
        source_id=source["id"],
        path="model.json",
        file_revision=revision(path.stat()),
        block_cells=1024,
    )
    return args, arrays, grid, folder


def imported(service, tmp_path):
    args, arrays, grid, folder = fixture_source(service, tmp_path)
    inspected = service.invoke("source_inspect", {k: args[k] for k in ("source_id", "path", "file_revision")})
    assert inspected["cells"] == 13 * 17 * 19 and inspected["scope"].startswith("headers only")
    props = service.wait(service.invoke("grid_import", args))
    return args, arrays, grid, folder, props


def test_chunk_boundaries_axis_order_fractional_contacts_and_independent_evidence(service, tmp_path):
    args, arrays, grid, _, props = imported(service, tmp_path)
    assert props["summary"]["active_cells"] == int(arrays["active"].sum())
    bound = dict(props, paths={"grid.zip": str(service.store.path(props, "grid.zip"))})
    for contact in [-210, -142.75, -60]:
        p = dict(zone_ids=[2], contact_z_m=contact, bo=1.13)
        actual = evaluate(bound, [p])[0]
        assert actual == pytest.approx(volumes(arrays, grid, **p)["values"], rel=1e-11, abs=1e-8)
        assert actual == pytest.approx(
            reference_volumes(arrays, grid, [2], contact, 1.13), rel=1e-11, abs=1e-8
        )
    checked = service.wait(
        service.invoke("result_validate", dict(project_id=args["project_id"], artifact=ref(props)))
    )
    assert checked["summary"]["status"] == "PASS"


def test_large_properties_plan_uncertainty_and_report_survive_revocation(service, tmp_path):
    args, _, _, folder, props = imported(service, tmp_path)
    LocalSources(service.store).remove(args["source_id"])
    (folder / "phi.npy").unlink()
    pid = args["project_id"]
    plan = service.invoke(
        "calculation_plan",
        dict(
            project_id=pid,
            properties=ref(props),
            zone_ids=[1, 2],
            bo=1.2,
            contacts=[dict(name="partial", z_m=-142.75)],
            assumptions=["Synthetic Cartesian variable properties"],
            uncertainty=dict(
                contact_name="partial",
                count=4,
                seed=42,
                distributions=dict(phi=dict(kind="uniform", low=0.15, high=0.25)),
            ),
        ),
    )
    submitted = service.invoke("calculation_run", dict(project_id=pid, plan=ref(plan)))
    service.wait(submitted)
    status = service.invoke("calculation_status", dict(project_id=pid, run_id=submitted["run_id"]))
    report = service.store.object(pid, status["report"])
    assert report["summary"]["validation_status"] == "PASS"
    result = json.loads(service.store.path(report, "report.json").read_text())
    assert result["specification"]["properties"] == ref(props)
    assert result["uncertainty"]["backend"] == "chunked-cpu"


@pytest.mark.parametrize("invalid", ["changed", "fortran", "object", "units", "escape", "symlink"])
def test_unsafe_or_ambiguous_large_import_rejected_before_compute(service, tmp_path, invalid):
    args, arrays, grid, folder = fixture_source(service, tmp_path)
    path = folder / "model.json"
    manifest = json.loads(path.read_text())
    if invalid == "changed":
        (folder / "phi.npy").write_bytes(b"changed")
    elif invalid in ("fortran", "object"):
        np.save(
            folder / "phi.npy",
            np.asfortranarray(arrays["phi"])
            if invalid == "fortran"
            else np.full(grid["shape"], "arbitrary", dtype=object),
        )
        manifest["arrays"]["phi"]["file_revision"] = revision((folder / "phi.npy").stat())
    elif invalid == "units":
        manifest["units"]["phi"] = "percent"
    elif invalid == "escape":
        manifest["arrays"]["phi"]["path"] = "../outside.npy"
    else:
        (folder / "phi.npy").unlink()
        (folder / "phi.npy").symlink_to(folder / "ntg.npy")
    path.write_text(json.dumps(manifest))
    args["file_revision"] = revision(path.stat())
    with pytest.raises((DomainError, ValueError)):
        service.invoke("grid_import", args)
    assert service.store.list_jobs(args["project_id"]) == []


def test_missing_chunk_with_valid_blob_hash_never_uses_zarr_fill_values(service, tmp_path):
    args, _, _, _, props = imported(service, tmp_path)
    damaged = tmp_path / "missing.zip"
    with zipfile.ZipFile(service.store.path(props, "grid.zip")) as old, zipfile.ZipFile(damaged, "w") as new:
        for name in old.namelist():
            if name != "phi/1":
                new.writestr(name, old.read(name))
    broken = service.store.publish(args["project_id"], "properties", props["summary"], {"grid.zip": damaged})
    validation = service.wait(
        service.invoke("result_validate", dict(project_id=args["project_id"], artifact=ref(broken)))
    )
    assert validation["summary"]["status"] == "FAIL"
    with pytest.raises(DomainError):
        service.wait(
            service.invoke(
                "volumetrics_calculate",
                dict(
                    project_id=args["project_id"],
                    properties=ref(broken),
                    zone_ids=[1],
                    contact_z_m=-140,
                    bo=1.2,
                ),
            )
        )


def grdecl_source(service, tmp_path):
    from opensubsurface.adapters.grdecl_properties import FORMAT as GRDECL_FORMAT

    args, arrays, grid, folder = fixture_source(service, tmp_path)
    manifest = json.loads((folder / "model.json").read_text())
    manifest["format"] = GRDECL_FORMAT
    manifest["cartesian_basis"] = "Synthetic uniform Cartesian control; no corner-point geometry"
    keywords = dict(
        active="ACTNUM",
        zones="FIPNUM",
        phi="PORO",
        ntg="NTG",
        sw="SWAT",
        permeability_md="PERMX",
        kz_ratio="PERMZ",
    )
    for name, data in arrays.items():
        if name == "kz_ratio":
            data = data * arrays["permeability_md"]
        values = np.nan_to_num(to_opm(data), nan=1e20)
        path = folder / (keywords[name] + ".grdecl")
        with path.open("w") as stream:
            stream.write("-- Synthetic ECLIPSE order: I fastest, K down\n" + keywords[name] + "\n")
            for value in values:
                stream.write("1*" + format(float(value), ".17e").replace("e", "D") + "\n")
            stream.write("/ -- end property\n")
        manifest["arrays"][name] = dict(
            path=path.name, file_revision=revision(path.stat()), keyword=keywords[name]
        )
    (folder / "model.json").write_text(json.dumps(manifest))
    args["file_revision"] = revision((folder / "model.json").stat())
    return args, arrays, grid, folder


def test_eclipse_property_stream_mapping_permz_ratio_and_independent_reference(service, tmp_path):
    args, arrays, grid, _ = grdecl_source(service, tmp_path)
    props = service.wait(service.invoke("grid_import", args))
    assert props["summary"]["order"] == "ECLIPSE"
    bound = dict(props, paths={"grid.zip": str(service.store.path(props, "grid.zip"))})
    for contact in (-200, -142.75, -70):
        case = dict(zone_ids=[2], contact_z_m=contact, bo=1.13)
        assert evaluate(bound, [case])[0] == pytest.approx(volumes(arrays, grid, **case)["values"], rel=1e-11)
    volume = service.wait(
        service.invoke(
            "volumetrics_calculate",
            dict(
                project_id=args["project_id"],
                properties=ref(props),
                zone_ids=[2],
                contact_z_m=-142.75,
                bo=1.13,
            ),
        )
    )
    validation = service.wait(
        service.invoke("result_validate", dict(project_id=args["project_id"], artifact=ref(volume)))
    )
    assert validation["summary"]["status"] == "PASS"


def test_large_eclipse_runs_and_explicit_constants_exceed_old_cell_limit(service, tmp_path):
    args, _, _, folder = grdecl_source(service, tmp_path)
    manifest = json.loads((folder / "model.json").read_text())
    manifest["grid"] = dict(shape=[64, 64, 1025], extent=[0, 64, 0, 64, -1025, 0])
    values = dict(active=1, zones=1, ntg=0.8, sw=0.25, permeability_md=100, kz_ratio=0.1)
    for name, value in values.items():
        manifest["arrays"][name] = dict(constant=value)
    path = folder / "PORO.grdecl"
    path.write_text("PORO\n4198400*0.2 /\n")
    manifest["arrays"]["phi"]["file_revision"] = revision(path.stat())
    (folder / "model.json").write_text(json.dumps(manifest))
    args.update(file_revision=revision((folder / "model.json").stat()), block_cells=262144)
    props = service.wait(service.invoke("grid_import", args))
    volume = service.wait(
        service.invoke(
            "volumetrics_calculate",
            dict(
                project_id=args["project_id"], properties=ref(props), zone_ids=[1], contact_z_m=-1025, bo=1.2
            ),
        )
    )
    assert props["summary"]["cells"] == 4198400
    assert volume["summary"]["values"]["STOIIP"] == pytest.approx(419840)


@pytest.mark.parametrize("bad", ["defaults", "extra", "short", "geometry"])
def test_eclipse_rejects_implicit_defaults_full_decks_and_wrong_counts(service, tmp_path, bad):
    args, _, _, folder = grdecl_source(service, tmp_path)
    path = folder / "PORO.grdecl"
    path.write_text(
        {
            "defaults": "PORO\n4199* /",
            "extra": "PORO\n4199*.2 / INCLUDE 'x' /",
            "short": "PORO\n4198*.2 /",
            "geometry": "COORD\n4199*.2 /",
        }[bad]
    )
    manifest = json.loads((folder / "model.json").read_text())
    manifest["arrays"]["phi"]["file_revision"] = revision(path.stat())
    (folder / "model.json").write_text(json.dumps(manifest))
    args["file_revision"] = revision((folder / "model.json").stat())
    with pytest.raises(DomainError):
        service.wait(service.invoke("grid_import", args))
    assert all(obj["kind"] != "properties" for obj in service.store.list_objects(args["project_id"]))
