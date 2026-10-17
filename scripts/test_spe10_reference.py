"""Offline upstream SPE10 static acceptance; run fetch_spe10_reference.py first.

Actual upstream PORO/PERMX/PERMZ + verified Cartesian FIELD geometry. Explicit NTG=1,
Sw=.2, Bo=1 are numerical-control assumptions, not OPM initialization or field reserves.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np

from opensubsurface.adapters.grdecl_properties import FORMAT
from opensubsurface.adapters.large_grid import UNITS
from opensubsurface.adapters.local_sources import LocalSources, path_revision
from opensubsurface.persistence.store import file_hash
from opensubsurface.service import Service, ref

ROOT = Path("examples/reference/spe10model2")
CELLS = 60 * 220 * 85
FT = 0.3048


def extract(path, output, keywords):
    """Split this pinned multi-keyword INC without interpreting arbitrary deck commands."""
    destination = None
    seen = set()
    header = b"-- Derived from pinned OPM SPE10 model2; original notices in ../raw\n-- ODbL-1.0 / DbCL-1.0; see ../sources.json\n"
    try:
        with path.open("rb") as stream:
            for line in stream:
                if len(line) > 65536:
                    raise ValueError("Unexpected upstream line length")
                text = line.split(b"--", 1)[0].strip()
                if destination is None:
                    if not text:
                        continue
                    name = text.decode("ascii")
                    if name not in keywords or name in seen:
                        raise ValueError("Unexpected upstream property: " + name)
                    destination = (output / (name + ".grdecl")).open("wb")
                    destination.write(header + line)
                    seen.add(name)
                else:
                    destination.write(line)
                    if b"/" in text:
                        destination.close()
                        destination = None
        if destination is not None or seen != set(keywords):
            raise ValueError("Incomplete upstream properties")
    finally:
        if destination:
            destination.close()


def independent_values(path, keyword):
    # A separate NumPy parser for this literal-value upstream fixture, not the production parser.
    text = " ".join(line.split("--", 1)[0] for line in path.read_text().splitlines())
    tokens = text.split()
    if tokens[0] != keyword or tokens[-1] != "/" or any("*" in x for x in tokens[1:-1]):
        raise ValueError("This independent reader expects the pinned literal-value fixture")
    values = np.fromstring(" ".join(tokens[1:-1]), sep=" ")
    if len(values) != CELLS or not np.isfinite(values).all():
        raise ValueError("Upstream values/count invalid")
    return values


def prepare():
    sources = json.loads((ROOT / "sources.json").read_text())
    for entry in sources["files"]:
        if file_hash(ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError("Source hash mismatch: " + entry["path"])
    output = ROOT / "prepared"
    output.mkdir(exist_ok=True)
    extract(ROOT / "raw/SPE10MODEL2_PHI.INC", output, ["PORO"])
    extract(ROOT / "raw/SPE10MODEL2_PERM.INC", output, ["PERMX", "PERMY", "PERMZ"])
    deck = (ROOT / "raw/SPE10_MODEL2.DATA").read_text()
    cleaned = " ".join(line.split("--", 1)[0] for line in deck.splitlines()).split()
    for keyword, expected in dict(
        DIMENS=["60", "220", "85"], DX=["1122000*20"], DY=["1122000*10"], DZ=["1122000*2"]
    ).items():
        index = cleaned.index(keyword) + 1
        if cleaned[index : index + len(expected)] != expected or cleaned[index + len(expected)] != "/":
            raise ValueError("Geometry differs from pinned Cartesian fixture")
    if "FIELD" not in cleaned:
        raise ValueError("Expected FIELD units")
    tops = (ROOT / "raw/SPE10MODEL2_TOPS.INC").read_text().split()
    expected = ["TOPS"] + ["13200*" + str(z) for z in range(12000, 12170, 2)] + ["/"]
    if tops != expected:
        raise ValueError("TOPS is not the expected flat regular Cartesian layering")
    arrays = {name: dict(constant=v) for name, v in dict(active=1, zones=1, ntg=1, sw=0.2).items()}
    for name, keyword in dict(phi="PORO", permeability_md="PERMX", kz_ratio="PERMZ").items():
        path = output / (keyword + ".grdecl")
        arrays[name] = dict(path=path.name, file_revision=path_revision(path), keyword=keyword)
    grid = dict(shape=[60, 220, 85], extent=[0, 1200 * FT, 0, 2200 * FT, -12170 * FT, -12000 * FT])
    manifest = dict(
        format=FORMAT,
        grid=grid,
        crs="LOCAL_METRIC",
        vertical_datum="SPE10_DEPTH_REFERENCE_UNSPECIFIED",
        z_direction="up",
        units=UNITS,
        arrays=arrays,
        cartesian_basis="Verified original DIMENS, FIELD, constant DX20/DY10/DZ2 ft and all TOPS12000+2*k; origin X=Y=0 local, Z=-depth*ft",
    )
    (output / "model.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest, sources


def run(args):
    manifest, sources = prepare()
    phi = independent_values(ROOT / "prepared/PORO.grdecl", "PORO")
    kx = independent_values(ROOT / "prepared/PERMX.grdecl", "PERMX")
    ky = independent_values(ROOT / "prepared/PERMY.grdecl", "PERMY")
    kz = independent_values(ROOT / "prepared/PERMZ.grdecl", "PERMZ")
    stats = dict(
        phi_min=float(phi.min()),
        phi_max=float(phi.max()),
        kx_min_md=float(kx.min()),
        kx_max_md=float(kx.max()),
        kz_min_md=float(kz.min()),
        kz_max_md=float(kz.max()),
        kz_over_kx_max=float(np.max(kz / kx)),
        kx_equals_ky=bool(np.array_equal(kx, ky)),
    )
    print(json.dumps(dict(source_statistics=stats), indent=2), flush=True)
    evidence = dict(
        dataset="OPM SPE10 model2",
        commit=sources["commit"],
        cells=CELLS,
        source_statistics=stats,
        scope="Upstream benchmark, not real field; static property/volume checks, not OPM forecast",
        assumptions=[
            "Source geometry converted FIELD feet to metres; local X/Y origin0, unspecified source depth datum",
            "All cells active; one zone; explicit NTG=1, Sw=.2, Bo=1 solely for numerical control",
            "Preserve published PORO exactly, including remaining zeros, and original permeability; PERMY checked equal to PERMX",
        ],
        source_files=sources["files"],
        contacts=[],
        status="NOT RUN",
    )
    output = ROOT / "results"
    output.mkdir(exist_ok=True)
    service = Service(args.state)
    try:
        pid = service.invoke(
            "project_create",
            dict(
                name="Upstream SPE10 model2 — static control",
                crs=manifest["crs"],
                vertical_datum=manifest["vertical_datum"],
            ),
        )["id"]
        source = LocalSources(service.store).register("OPM SPE10 prepared", ROOT / "prepared")
        properties = service.wait(
            service.invoke(
                "grid_import",
                dict(
                    project_id=pid,
                    source_id=source["id"],
                    path="model.json",
                    file_revision=path_revision((ROOT / "prepared/model.json")),
                    block_cells=65536,
                ),
            ),
            timeout=300,
        )
        # Exact preservation of imported published arrays, checked outside production QC/integration.
        from opensubsurface.adapters.large_grid import open_grid

        bound = dict(properties, paths={"grid.zip": str(service.store.path(properties, "grid.zip"))})
        preserved = True
        with open_grid(bound) as group:
            for start in range(0, CELLS, 65536):
                stop = min(start + 65536, CELLS)
                preserved &= np.array_equal(group["phi"][start:stop], phi[start:stop])
                preserved &= np.array_equal(group["permeability_md"][start:stop], kx[start:stop])
                preserved &= np.allclose(
                    group["kz_ratio"][start:stop], kz[start:stop] / kx[start:stop], rtol=0, atol=0
                )
        evidence["published_properties_preserved"] = bool(preserved)
        if not preserved:
            raise ValueError("Imported properties changed")
        depths = [12170, 12085.5, 12000]
        plan = service.invoke(
            "calculation_plan",
            dict(
                project_id=pid,
                properties=ref(properties),
                name="OPM SPE10 model2 — upstream properties / static numerical control",
                zone_ids=[1],
                bo=1,
                contacts=[
                    dict(name=name, z_m=-depth * FT)
                    for name, depth in zip(["full_control", "fractional_control", "dry_control"], depths)
                ],
                assumptions=evidence["assumptions"],
            ),
        )
        submitted = service.invoke("calculation_run", dict(project_id=pid, plan=ref(plan)))
        service.wait(submitted, timeout=300)
        status = service.invoke("calculation_status", dict(project_id=pid, run_id=submitted["run_id"]))
        report = service.store.object(pid, status["report"])
        result = json.loads(service.store.path(report, "report.json").read_text())
        layer_phi = phi.reshape(85, 220, 60).sum(axis=(1, 2), dtype=np.float64)
        all_close = True
        for row, depth in zip(result["contacts"], depths):
            oil_thickness_ft = np.clip(depth - (12000 + 2 * np.arange(85)), 0, 2)
            pv = math.fsum(float(v) * float(h) * 20 * 10 * FT**3 for v, h in zip(layer_phi, oil_thickness_ft))
            expected = dict(
                GRV=CELLS * 400 * FT**3,
                GRV_oil_interval=60 * 220 * 20 * 10 * FT**3 * float(oil_thickness_ft.sum()),
                NetRockVolume=60 * 220 * 20 * 10 * FT**3 * float(oil_thickness_ft.sum()),
                PV=pv,
                HCPV=pv * 0.8,
                STOIIP=pv * 0.8,
            )
            ok = all(math.isclose(row[k], v, rel_tol=1e-8, abs_tol=1e-7) for k, v in expected.items())
            all_close &= ok
            evidence["contacts"].append(
                dict(
                    name=row["name"],
                    depth_ft=depth,
                    expected=expected,
                    actual={k: row[k] for k in expected},
                    independent_source_sum="PASS" if ok else "FAIL",
                )
            )
        evidence.update(
            project_id=pid,
            run_id=submitted["run_id"],
            plan=ref(plan),
            report=ref(report),
            validation=result["validation_status"],
            status="PASS" if all_close and result["validation_status"] == "PASS" else "FAIL",
        )
        for filename in ("report.html", "report.md", "report.json", "volumes.csv", "volumes.png"):
            (output / filename).write_bytes(service.store.path(report, filename).read_bytes())
    except Exception as error:
        evidence.update(status="FAIL", error=dict(type=type(error).__name__, message=str(error)))
        raise
    finally:
        service.close()
        (output / "acceptance.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            dict(
                status=evidence["status"],
                validation=evidence["validation"],
                cells=CELLS,
                stoiip_standard_m3=[r["actual"]["STOIIP"] for r in evidence["contacts"]],
                output=str(output.resolve()),
            ),
            indent=2,
        )
    )
    if evidence["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=ROOT / "state")
    run(parser.parse_args())
