"""Bounded oil-water Cartesian exporter. Not a substitute for the OPM solver."""

import json
import shutil
import subprocess
import sys
from datetime import timezone

import numpy as np
from scipy.ndimage import label

from opensubsurface.domain.numerics import from_opm, grid_arrays, to_opm, validate_properties
from opensubsurface.errors import DomainError, require
from opensubsurface.execution.provenance import solver_identity


def keyword(name, values):
    flat = np.asarray(values).ravel()
    return (
        name
        + "\n"
        + "\n".join(" ".join(f"{x:.12g}" for x in flat[i : i + 8]) for i in range(0, len(flat), 8))
        + "\n/\n"
    )


def generate_case(p, arrays, grid, out, model_summary):
    require(
        not model_summary.get("fault"),
        "UNSUPPORTED_GRID_BRIDGE",
        "An inclined geological fault cannot be passed to Cartesian OPM automatically",
    )
    require(
        p["demo_assumptions_accepted"],
        "INVALID_PVT",
        "The profile uses named demo PVT/SCAL; confirm these assumptions",
    )
    validate_properties(arrays)
    nx, ny, nz = shape = tuple(grid["shape"])
    require(nx >= 2 and ny >= 2, "UNSUPPORTED_GRID_BRIDGE", "Demo wells require nx, ny >= 2")
    active = arrays["active"].astype(bool)
    require(
        ((arrays["phi"] * arrays["ntg"])[active] > 0).all(),
        "UNSUPPORTED_GRID_BRIDGE",
        "For the supported OPM bridge active cells must have positive PORV",
    )
    components, n = label(active)
    require(n == 1, "QC_FAILED", "The active region is not connected")
    require(active[0, 0].all() and active[-1, -1].all(), "QC_FAILED", "Completion in an inactive cell")
    centers, spacing = grid_arrays(grid)
    dx, dy, dz = spacing
    fluid = p["fluid"]
    # Datum: z=0 maps to simulation depth=0. All tops positive in this profile.
    top_depth = -grid["extent"][5]
    require(top_depth >= 0, "UNSUPPORTED_GRID_BRIDGE", "The demo profile requires Z <= 0")
    count = nx * ny * nz
    deck = "-- Kanysh Basic synthetic demo; units METRIC, pressure absolute bar\n"
    deck += f"RUNSPEC\nTITLE\n Kanysh Basic {p['profile']}\nDIMENS\n {nx} {ny} {nz} /\n"
    deck += "OIL\nWATER\nMETRIC\nUNIFOUT\n"
    deck += "TABDIMS\n 1 1 20 20 1 20 /\nWELLDIMS\n 2 " + str(nz) + " 1 2 /\n"
    import datetime

    d = datetime.date.fromisoformat(p["start_date"])
    deck += f"START\n {d.day} '{d.strftime('%b').upper()}' {d.year} /\nGRID\nINIT\n"
    for name, value in [("DX", dx), ("DY", dy), ("DZ", dz)]:
        deck += f"{name}\n {count}*{value:.12g} /\n"
    deck += f"TOPS\n {nx * ny}*{top_depth:.12g} /\n"
    for name, field in [
        ("ACTNUM", active),
        ("PORO", arrays["phi"]),
        ("NTG", arrays["ntg"]),
        ("PERMX", arrays["permeability_md"]),
        ("PERMY", arrays["permeability_md"]),
        ("PERMZ", arrays["permeability_md"] * arrays["kz_ratio"]),
    ]:
        deck += keyword(name, to_opm(np.where(active, field, 0)))
    deck += "PROPS\n"
    deck += f"STCOND\n {fluid['standard_temperature_c']} {fluid['standard_pressure_bara']} /\n"
    deck += f"DENSITY\n {fluid['oil_density_kg_m3']} {fluid['water_density_kg_m3']} 1.2 /\n"
    deck += f"PVTW\n {fluid['reference_pressure_bara']} {fluid['bw']} 0 {fluid['water_viscosity_cp']} 0 /\n"
    deck += f"PVDO\n 1 {fluid['bo']} {fluid['oil_viscosity_cp']}\n 1000 {fluid['bo']} {fluid['oil_viscosity_cp']} /\n"
    deck += f"ROCK\n {fluid['reference_pressure_bara']} {fluid['rock_compressibility_per_bar']} /\n"
    deck += "SWOF\n" + "\n".join(" ".join(str(x) for x in row) for row in fluid["swof"]) + "\n/\n"
    deck += "SOLUTION\n"
    # Explicit pressure with hydrostatic gradient, initialized oil-water mixture.
    reference_z = float(centers[..., 2].mean())
    rho_mix = (
        fluid["oil_density_kg_m3"] / fluid["bo"] * (1 - arrays["sw"])
        + fluid["water_density_kg_m3"] / fluid["bw"] * arrays["sw"]
    )
    pressure = fluid["reference_pressure_bara"] + rho_mix * 9.80665 * (reference_z - centers[..., 2]) / 1e5
    require((pressure[active] > 0).all(), "INVALID_PVT", "Non-positive initial pressure")
    require(
        (
            (arrays["sw"][active] >= fluid["swof"][0][0]) & (arrays["sw"][active] <= fluid["swof"][-1][0])
        ).all(),
        "INVALID_PVT",
        "Sw is outside the SCAL endpoints",
    )
    deck += keyword("PRESSURE", to_opm(pressure)) + keyword("SWAT", to_opm(arrays["sw"]))
    deck += "RPTRST\n BASIC=2 /\nSUMMARY\nFPR\nFOPT\nFWPT\nFWIT\nFOPR\nFWPR\n"
    deck += "SCHEDULE\n"
    if p["profile"] != "no_flow":
        deck += "WELSPECS\n 'PROD' 'FIELD' 1 1 1* 'OIL' /\n"
        if p["profile"] == "waterflood":
            deck += f" 'INJ' 'FIELD' {nx} {ny} 1* 'WATER' /\n"
        deck += "/\nCOMPDAT\n"
        deck += f" 'PROD' 1 1 1 {nz} 'OPEN' 1* 1* 0.2 /\n"
        if p["profile"] == "waterflood":
            deck += f" 'INJ' {nx} {ny} 1 {nz} 'OPEN' 1* 1* 0.2 /\n"
        deck += "/\nWCONPROD\n"
        deck += f" 'PROD' 'OPEN' 'ORAT' {p['producer_rate_sm3_day']} 4* {p['producer_bhp_bara']} /\n/\n"
        if p["profile"] == "waterflood":
            deck += f"WCONINJE\n 'INJ' 'WATER' 'OPEN' 'RATE' {p['injector_rate_sm3_day']} 1* {p['injector_bhp_bara']} /\n/\n"
    deck += "TSTEP\n" + " ".join(str(x) for x in np.diff([0] + p["report_days"])) + " /\nEND\n"
    (out / "CASE.DATA").write_text(deck, encoding="utf-8")
    idx = np.arange(count).reshape(shape)
    np.savez_compressed(
        out / "initial_state.npz",
        sw=arrays["sw"],
        pressure=pressure,
        pore_volume=np.where(active, np.prod(spacing) * arrays["phi"] * arrays["ntg"], 0),
    )
    np.savez_compressed(
        out / "mapping.npz",
        geological_ids=idx,
        simulator_linear_index=from_opm(np.arange(count), shape),
        simulator_order_geological_ids=to_opm(idx),
        active=active,
        centers=centers,
    )
    pv = float(np.sum(np.prod(spacing) * arrays["phi"][active] * arrays["ntg"][active]))
    summary = dict(
        profile=p["profile"],
        grid=grid,
        units="METRIC",
        pressure="bara",
        ntg_convention="PORO net-rock; NTG separate keyword (not applied twice)",
        input_pore_volume_m3=pv,
        bo=fluid["bo"],
        bw=fluid["bw"],
        rock_compressibility_per_bar=fluid["rock_compressibility_per_bar"],
        standard_conditions=dict(
            temperature_k=fluid["standard_temperature_c"] + 273.15,
            pressure_pa=fluid["standard_pressure_bara"] * 1e5,
        ),
        start_date=p["start_date"],
        initialization_profile="fresh_explicit",
        report_days=p["report_days"],
        initialization="explicit pressure/saturation; hydrostatic mixed density approximation",
        solver_validation="NOT RUN: requires pinned OPM binary and conservation checks",
        assumptions="Synthetic demo PVT/SCAL, not measured; closed boundaries",
    )
    return (
        "simulation_case",
        summary,
        {
            "CASE.DATA": out / "CASE.DATA",
            "mapping.npz": out / "mapping.npz",
            "initial_state.npz": out / "initial_state.npz",
        },
    )


def run_case(case_files, p, out):
    require(
        sys.platform == "linux",
        "SOLVER_PLATFORM_UNSUPPORTED",
        "OPM Flow requires Linux/WSL; native Windows simulation is unavailable",
        remediation="Run hydrodynamics in a Linux/WSL installation; static calculations work natively.",
    )
    identity = solver_identity()
    require(
        identity is not None,
        "SOLVER_UNAVAILABLE",
        "OPM Flow is not installed",
        remediation="Install the pinned OPM in a Linux worker; see docs/SUPPORTED_PROFILES.md",
    )
    require(
        p["execution"]["device_policy"] != "require_gpu",
        "NO_COMPATIBLE_GPU",
        "The CUDA solver profile has not passed the reference benchmark yet",
    )
    context = p["_case_summary"]
    require(
        "standard_conditions" in context, "INPUT_REVISION_CONFLICT", "Recreate the case with explicit STCOND"
    )
    from opensubsurface.domain.results import StandardConditions

    StandardConditions.model_validate(context["standard_conditions"])
    require(
        all(name in case_files for name in ("CASE.DATA", "mapping.npz", "initial_state.npz")),
        "INPUT_REVISION_CONFLICT",
        "Recreate the case with initial state and GridMapping",
    )
    try:
        from resdata.grid import Grid  # noqa: F401
        from resdata.resfile import ResdataFile, ResdataRestartFile  # noqa: F401
        from resdata.summary import Summary  # noqa: F401
    except ImportError:
        raise DomainError("RESULT_READER_UNAVAILABLE", "Install the solver extra (resdata)")
    run_dir = out / "solver"
    run_dir.mkdir()
    deck = run_dir / "CASE.DATA"
    shutil.copyfile(case_files["CASE.DATA"], deck)
    with (out / "solver.log").open("w") as log:
        result = subprocess.run(
            [identity["path"], str(deck), "--output-dir=" + str(run_dir)],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    require(result.returncode == 0, "COMPUTE_FAILED", "OPM exited with an error; the log is saved")
    require(
        all((run_dir / f"CASE.{ext}").is_file() for ext in ("SMSPEC", "UNSMRY", "UNRST", "INIT", "EGRID")),
        "INCOMPLETE_OUTPUT",
        "The solver did not produce the required results",
    )
    summary = read_summary(run_dir / "CASE.SMSPEC", context["standard_conditions"])
    require(
        summary["elapsed_days"][-1] >= p["_case_summary"]["report_days"][-1] - 1e-5,
        "INCOMPLETE_OUTPUT",
        "The solver did not complete the report schedule",
    )
    require(
        all(
            np.isclose(summary["elapsed_days"], day, atol=1e-5, rtol=0).any()
            for day in context["report_days"]
        ),
        "INCOMPLETE_OUTPUT",
        "Summary does not contain all requested report dates",
    )
    (out / "series.json").write_text(json.dumps(summary, allow_nan=False), encoding="utf-8")
    from opensubsurface.adapters.results import read_restart_fields, write_series_csv

    fields_summary = read_restart_fields(run_dir, case_files["mapping.npz"], out / "states.zip")
    require(
        fields_summary["restart_days"][-1] >= context["report_days"][-1] - 1e-5,
        "INCOMPLETE_OUTPUT",
        "Restart snapshots do not cover the full report schedule",
    )
    from opensubsurface.adapters.results import conservation_report

    conservation = conservation_report(out / "states.zip", case_files["initial_state.npz"], summary, context)
    (out / "qc_report.json").write_text(json.dumps(conservation, allow_nan=False), encoding="utf-8")
    require(
        conservation["status"] != "FAIL",
        "CONSERVATION_FAILED",
        "Component balance / initialization QC failed; see job diagnostics",
    )
    require(
        all(
            np.isclose(fields_summary["restart_days"], day, atol=1e-5, rtol=0).any()
            for day in context["report_days"]
        ),
        "INCOMPLETE_OUTPUT",
        "Restart does not contain all requested report dates",
    )
    write_series_csv(summary, out / "series.csv")
    shutil.copyfile(case_files["mapping.npz"], out / "mapping.npz")
    files = {f.name: f for f in run_dir.iterdir() if f.is_file()}
    files.update(
        {
            "solver.log": out / "solver.log",
            "series.json": out / "series.json",
            "series.csv": out / "series.csv",
            "states.zip": out / "states.zip",
            "mapping.npz": out / "mapping.npz",
            "qc_report.json": out / "qc_report.json",
        }
    )
    return (
        "simulation_result",
        dict(
            backend="opm-cpu",
            solver_identity=identity,
            final_day=summary["elapsed_days"][-1],
            vectors=list(summary["vectors"]),
            grid=context["grid"],
            standard_conditions=context["standard_conditions"],
            conservation=conservation,
            **fields_summary,
        ),
        files,
    )


def read_summary(path, standard_conditions):
    from opensubsurface.domain.results import VECTOR_KINDS, normalize_series

    try:
        from resdata.summary import Summary
    except ImportError:
        raise DomainError("RESULT_READER_UNAVAILABLE", "Install the solver extra (resdata)")
    reader = Summary(str(path))
    keys = list(VECTOR_KINDS)
    keys.extend(str(k) for k in reader.keys("WBHP:*"))
    vectors = {}
    for key in keys:
        if key == "WATER_CUT" or key not in reader:
            continue
        values = reader.numpy_vector(key)
        require(np.isfinite(values).all(), "INVALID_RESULTS", "NaN/Inf in summary " + key)
        vectors[key] = dict(
            values=values.tolist(),
            unit=reader.unit(key),
            kind="state" if key.startswith("WBHP:") else VECTOR_KINDS[key],
        )
    dates = [
        d.replace(tzinfo=timezone.utc).isoformat()
        if d.tzinfo is None
        else d.astimezone(timezone.utc).isoformat()
        for d in reader.dates
    ]
    return normalize_series(
        dict(
            schema_version=1,
            dates=dates,
            vectors=vectors,
            elapsed_days=list(map(float, reader.days)),
            standard_conditions=standard_conditions,
            completed=True,
            pressure_reference="absolute",
            provenance="OPM/Eclipse summary read by resdata; calendar interpreted as UTC",
        )
    )
