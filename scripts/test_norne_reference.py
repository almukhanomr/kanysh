"""Reproducible field geometry/property import → plan → independent clipping → 3D.

Static benchmark assumptions are explicit and are not the Norne history-matched initial state.
Run fetch_norne_reference.py first. Data retain upstream ODbL/DbCL attribution.
"""

import hashlib
import json
import shutil
import time
from pathlib import Path

import numpy as np
import xtgeo
from norne_demo_support import contacts, strict_contact_results

from opensubsurface.adapters.cornerpoint import FORMAT
from opensubsurface.adapters.large_grid import UNITS, open_grid
from opensubsurface.adapters.local_sources import LocalSources, path_revision
from opensubsurface.persistence.store import uid
from opensubsurface.service import Service, ref

ROOT = Path("examples/reference/norne")


def main():
    started = time.monotonic()
    sources = json.loads((ROOT / "sources.json").read_text())
    for entry in sources["files"]:
        assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    prepared = ROOT / "prepared"
    prepared.mkdir(exist_ok=True)
    geometry = prepared / "norne.grdecl"
    with geometry.open("wb") as stream:
        stream.write((ROOT / "raw/IRAP_1005.GRDECL").read_bytes())
        stream.write(b"\n")
        stream.write((ROOT / "raw/ACTNUM_0704.prop").read_bytes())
    declarations = {k: dict(constant=v) for k, v in dict(sw=0.25, kz_ratio=0.1).items()}
    for field, filename, keyword in [
        ("phi", "PORO_0704.prop", "PORO"),
        ("ntg", "NTG_0704.prop", "NTG"),
        ("permeability_md", "PERM_0704.prop", "PERMX"),
        ("zones", "FIPNUM_0704.prop", "FIPNUM"),
    ]:
        path = prepared / filename
        shutil.copyfile(ROOT / "raw" / filename, path)
        declarations[field] = dict(path=filename, keyword=keyword, file_revision=path_revision(path))
    assumptions = [
        "Public OPM Norne field benchmark geometry/ACTNUM/PORO/PERMX/NTG/FIPNUM; pinned source commit",
        "Coordinates metres, Z = negative source depth; CRS/datum not independently established",
        "Explicit benchmark constants Sw=0.25, Kz/Kx=0.1, Bo=1.2; not Norne dynamic initialization",
        "Three uniform OWC sensitivity alternatives selected from full-deck EQUIL inside active geometry; not regional equilibrium",
        "Warped corner-point cells use six tetrahedra along diagonal 0–7",
    ]
    manifest = dict(
        format=FORMAT,
        shape=[46, 112, 22],
        geometry=dict(path=geometry.name, format="grdecl", file_revision=path_revision(geometry)),
        crs="LOCAL_METRIC",
        vertical_datum="NORNE_SOURCE_DEPTH_DATUM_UNVERIFIED",
        length_unit="m",
        z_direction="down",
        units=UNITS,
        arrays=declarations,
        assumptions=assumptions,
    )
    path = prepared / "model.json"
    path.write_text(json.dumps(manifest, indent=2))
    service = Service(ROOT / "state" / uid("publication"))
    try:
        pid = service.invoke(
            "project_create",
            dict(name="Norne public corner-point reference", vertical_datum=manifest["vertical_datum"]),
        )["id"]
        source = LocalSources(service.store).register("Norne prepared", prepared)
        props = service.wait(
            service.invoke(
                "grid_import",
                dict(
                    project_id=pid,
                    source_id=source["id"],
                    path="model.json",
                    file_revision=path_revision(path),
                ),
            )
        )
        print("Imported", props["summary"]["active_cells"], "active cells", flush=True)
        native = xtgeo.grid_from_file(geometry, fformat="grdecl")
        bound = dict(props, paths={"grid.zip": str(service.store.path(props, "grid.zip"))})
        with open_grid(bound) as group:
            active = group["active"][:]
            assert np.array_equal(active, native.get_actnum(asmasked=False).values.ravel().astype(bool))
            for field, filename, keyword in [
                ("phi", "PORO_0704.prop", "PORO"),
                ("ntg", "NTG_0704.prop", "NTG"),
                ("permeability_md", "PERM_0704.prop", "PERMX"),
                ("zones", "FIPNUM_0704.prop", "FIPNUM"),
            ]:
                original = xtgeo.gridproperty_from_file(
                    prepared / filename, fformat="grdecl", grid=native, name=keyword
                )
                assert np.array_equal(group[field][:][active], original.values.data.ravel()[active])
            for ijk in [(0, 0, 0), (10, 30, 5), (20, 60, 15), (45, 111, 21)]:
                flat = np.ravel_multi_index(ijk, native.dimensions)
                expected = np.asarray(
                    native.get_xyz_cell_corners(ijk=ijk, activeonly=False, zerobased=True)
                ).reshape(8, 3)
                expected[:, 2] *= -1
                assert np.array_equal(group["corners"][int(flat)], expected)
        with open_grid(bound) as group:
            active = group["active"][:].astype(bool)
            z = group["corners"][:][active, :, 2]
            selection = contacts(ROOT, float(-z.max()), float(-z.min()))
        assumptions.append("Contact selection: " + json.dumps(selection, sort_keys=True))
        plan = service.invoke(
            "calculation_plan",
            dict(
                project_id=pid,
                properties=ref(props),
                zone_ids=props["summary"]["zone_ids"],
                bo=1.2,
                contacts=[dict(name="depth-" + str(depth), z_m=-depth) for depth in selection["depths_m"]],
                assumptions=assumptions,
            ),
        )
        run = service.invoke("calculation_run", dict(project_id=pid, plan=ref(plan)))
        service.wait(run)
        status = service.invoke("calculation_status", dict(project_id=pid, run_id=run["run_id"]))
        report = service.store.object(pid, status["report"])
        assert report["summary"]["validation_status"] == "PASS", report["summary"]
        actual_report = json.loads(service.store.path(report, "report.json").read_text())
        distinction = strict_contact_results(actual_report["contacts"])
        print("Independent report validation and strictly different contacts PASS", flush=True)
        service.invoke(
            "scene_show",
            dict(
                project_id=pid,
                ref=ref(props),
                field="phi",
                opacity=1,
                cell_range=[0, 46 * 112 * 22],
                stride=1,
            ),
        )
        scene = service.wait(service.invoke("scene_export", dict(project_id=pid, max_cells=200000)))
        results = ROOT / "results"
        results.mkdir(exist_ok=True)
        for obj in (report, scene):
            for name in obj["files"]:
                shutil.copyfile(service.store.path(obj, name), results / name)
        acceptance = dict(
            status="PASS",
            cells=props["summary"]["cells"],
            active_cells=props["summary"]["active_cells"],
            shape=manifest["shape"],
            zone_ids=props["summary"]["zone_ids"],
            source_commit=sources["commit"],
            input_property_mapping="exact vs independent XTGeo property reader",
            corner_mapping="exact at four IJK control cells",
            volume_validation="independent SciPy convex-hull clipping",
            report_validation=report["summary"]["validation_status"],
            scene_backend=scene["summary"]["backend"],
            displayed_cells=scene["summary"]["displayed_cells"],
            elapsed_seconds=time.monotonic() - started,
            project_id=pid,
            run_id=run["run_id"],
            assumptions=assumptions,
            contact_selection=selection,
            contact_distinction=distinction,
        )
        (results / "acceptance.json").write_text(json.dumps(acceptance, indent=2) + "\n")
        # Curated public snapshot: this project only; no jobs or registered source roots.
        bundle = Path("src/opensubsurface/data/norne")
        archive = bundle / "project.zip"
        service.store.export_project(pid, archive)
        declaration = dict(
            project_id=pid,
            sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            scope="Saved public Norne static sensitivity benchmark with three distinct in-reservoir OWCs; explicit Sw/Bo, not field reserves or equilibrium initialization",
            license="ODbL-1.0 / DbCL-1.0, Statoil 2015; see bundled notices",
            source_commit=sources["commit"],
            contact_selection=selection,
            contact_distinction=distinction,
        )
        (bundle / "demo.json").write_text(json.dumps(declaration, indent=2) + "\n")
        print(json.dumps(acceptance, indent=2), flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    main()
