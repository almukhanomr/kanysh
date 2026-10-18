"""Stateless numerical worker: no metadata DB access, immutable inputs and temporary outputs."""

import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from opensubsurface.errors import require


class _Lazy:
    """Import heavy adapters (gstools, scipy.signal, segyio, OPM) only in the worker that uses them.

    Every job runs in a fresh process; eager imports cost ~2.5 s per node of a workflow.
    """

    def __init__(self, module):
        self._module = module

    def __getattr__(self, name):
        import importlib

        return getattr(importlib.import_module(self._module), name)


geostat = _Lazy("opensubsurface.adapters.geostat")
imports = _Lazy("opensubsurface.adapters.imports")
opm = _Lazy("opensubsurface.adapters.opm")
seismic = _Lazy("opensubsurface.adapters.seismic")
numerics = _Lazy("opensubsurface.domain.numerics")


def input_obj(request, name):
    return request["resolved"][name]


def load_arrays(obj):
    with np.load(obj["paths"]["arrays.npz"], allow_pickle=False) as data:
        return {k: data[k].copy() for k in data.files}


def save_arrays(out, arrays):
    np.savez_compressed(out / "arrays.npz", **arrays)
    return {"arrays.npz": out / "arrays.npz"}


def grid_of(obj):
    return obj["summary"]["grid"]


def run(request, out):
    operation, p = request["operation"], request["payload"]
    from opensubsurface.execution.blocks import settings

    device = request["device"]
    settings.set(dict(p.get("execution", {}), resolved_device=device))
    out = Path(out)
    out.mkdir(exist_ok=True, parents=True)
    if operation == "results_export":
        from opensubsurface.adapters.results_export import export

        return export(
            [request["resolved"][f"report_{i}"] for i in range(len(p["reports"]))],
            p,
            out,
            slices=[request["resolved"][f"slice_{i}"] for i in range(len(p["slices"]))],
        )
    if operation in ("sensitivity_tornado", "uncertainty_monte_carlo"):
        from opensubsurface.adapters.copilot_report import write_report
        from opensubsurface.adapters.regional_volumes import polygon_geometry
        from opensubsurface.adapters.sensitivity import monte_carlo, tornado

        objects = request["resolved"]
        polygon = polygon_geometry(objects["polygon"], p) if p.get("polygon") else None
        result = (tornado if operation == "sensitivity_tornado" else monte_carlo)(
            objects["properties"], p, out, polygon
        )
        files = write_report(out, operation, result)
        for name in ("tornado.png", "s_curve.png", "mc_samples.csv"):
            if (out / name).is_file():
                files[name] = out / name
        return (
            "analysis_report",
            dict(operation=operation, status=result["status"], validation_status=result["validation_status"]),
            files,
        )
    if operation == "wells_vs_model":
        from opensubsurface.adapters.copilot_report import write_report
        from opensubsurface.adapters.wells_vs_model import run as compare_logs

        objects = request["resolved"]
        result = compare_logs(
            objects["properties"],
            objects["trajectory"],
            [objects[f"las_{i}"] for i in range(len(p["logs"]))],
            p,
            out,
        )
        files = write_report(out, "Wells versus model", result)
        files["well_samples.csv"] = out / "well_samples.csv"
        return (
            "analysis_report",
            dict(operation=operation, status=result["status"], validation_status=result["validation_status"]),
            files,
        )
    if operation in ("regional_volumes", "volumes_reconcile", "model_diff"):
        from opensubsurface.adapters.copilot_report import write_report
        from opensubsurface.adapters.regional_volumes import evaluate, polygon_geometry

        objects = request["resolved"]
        obj = objects["properties"]
        polygon = polygon_geometry(objects["polygon"], p) if p.get("polygon") else None
        if operation == "model_diff":
            from opensubsurface.adapters.model_diff import run as compare_models

            result = compare_models(obj, objects["other_properties"], p, out)
        elif operation == "volumes_reconcile":
            from opensubsurface.adapters.source_files import copy_file
            from opensubsurface.adapters.volumes_reconcile import run as reconcile

            csv = out / "reference.csv"
            copy_file(request["source_context"], dict(path=p["path"], file_revision=p["file_revision"]), csv)
            result = reconcile(obj, p, csv, polygon)
        else:
            result = evaluate(obj, p, polygon)
        files = write_report(out, operation, result)
        for name in ("reference.csv", "changed_cells.csv"):
            if (out / name).is_file():
                files[name] = out / name
        return (
            "analysis_report",
            dict(
                operation=operation,
                status=result["status"],
                validation_status=result["validation_status"],
                changed_cells=result.get("changed_cells"),
            ),
            files,
        )
    if operation == "model_qc":
        from opensubsurface.adapters.copilot_report import write_report
        from opensubsurface.adapters.model_qc import run as run_qc

        result = run_qc(request["resolved"]["properties"], p, out)
        files = write_report(out, "Model QC", result)
        files["issues.csv"] = out / "issues.csv"
        return (
            "analysis_report",
            dict(
                operation=operation,
                status=result["status"],
                validation_status=result["validation_status"],
                counts=result["counts"],
            ),
            files,
        )
    if operation == "geodata_import":
        from opensubsurface.adapters.geodata import import_geodata

        return import_geodata(request["source_context"], p, request["resolved"], out)
    if operation == "eclipse_import":
        from opensubsurface.adapters.eclipse_import import import_deck

        return import_deck(request["source_context"], p, out)
    if operation == "grid_import":
        from opensubsurface.adapters.large_grid import import_grid

        return import_grid(request["source_context"], p["block_cells"], out)
    if operation == "scene_export":
        from opensubsurface.adapters.viewer import export_scene

        return export_scene(request["scene_context"], request["resolved"], p, out)
    if operation == "result_validate":
        from opensubsurface.calculations.validation import check_artifact

        artifact = input_obj(request, "artifact")
        evidence = check_artifact(artifact, {k: v for k, v in request["resolved"].items() if k != "artifact"})
        (out / "validation.json").write_text(
            json.dumps(evidence, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        return (
            "validation",
            {k: v for k, v in evidence.items() if k != "checks"},
            {"validation.json": out / "validation.json"},
        )
    if operation == "report_export":
        from opensubsurface.calculations.reporting import render

        return render(request["report_context"], request["resolved"], out)
    if operation == "dataset_import":
        return imports.import_dataset(Path(request["upload_path"]), p, out, request.get("dataset_context"))
    if operation == "fault_create":
        points = np.asarray(p["points"], float)
        normal = np.asarray(p["normal"], float)
        centered = points - points.mean(axis=0)
        span = max(float(np.linalg.norm(np.ptp(points, axis=0))), 1.0)
        require(
            np.linalg.matrix_rank(centered, tol=span * 1e-8) == 2,
            "QC_FAILED",
            "Точки должны задавать одну плоскость",
        )
        require(
            np.max(np.abs(centered @ normal)) <= span * 1e-6,
            "QC_FAILED",
            "Точки не лежат в плоскости с заданной нормалью",
        )
        geometry = dict(name=p["name"], points=p["points"], normal=p["normal"], relation=p["relation"])
        (out / "fault.json").write_text(json.dumps(geometry), encoding="utf-8")
        return (
            "fault",
            dict(profile="single_planar", geometry=geometry, units="m", relations=[[0, 1], [0, 0]]),
            {"fault.json": out / "fault.json"},
        )
    if operation == "model_build":
        require(
            not p.get("fault") or p["method"] == "gempy",
            "UNSUPPORTED_PROFILE",
            "Разлом поддерживается только GemPy",
        )
        grid = p["grid"]
        centers, _ = numerics.grid_arrays(grid)
        if p["method"] == "horizontal_explicit":
            require(p["horizontal_assumption"], "MISSING_ORIENTATIONS", "Явно выберите горизонтальные слои")
            horizons = np.asarray(p["horizons_z"])
            require(len(set(horizons)) == len(horizons), "QC_FAILED", "Повторяющиеся горизонты")
            require(
                all(grid["extent"][4] < h < grid["extent"][5] for h in horizons),
                "QC_FAILED",
                "Горизонт вне extent",
            )
            zones = np.searchsorted(np.sort(horizons), centers[..., 2]) + 1
            backend = "numpy-explicit-horizontal"
            extra = {}
        else:
            from opensubsurface.adapters.structure import gempy_build

            require("surfaces" in request["resolved"], "QC_FAILED", "GemPy требует surface points")
            surfaces = pq.read_table(input_obj(request, "surfaces")["paths"]["data.parquet"]).to_pandas()
            orientations = None
            if "orientations" in request["resolved"]:
                orientations = pq.read_table(
                    input_obj(request, "orientations")["paths"]["data.parquet"]
                ).to_pandas()
            fault = input_obj(request, "fault")["summary"]["geometry"] if p.get("fault") else None
            zones, extra = gempy_build(p, surfaces, orientations, device, fault)
            backend = "gempy-" + device
        arrays = dict(zones=zones.astype(np.int32), active=np.ones(tuple(grid["shape"]), bool))
        if p.get("fault"):
            geometry = input_obj(request, "fault")["summary"]["geometry"]
            sign = (centers - np.asarray(geometry["points"])[0]) @ np.asarray(geometry["normal"])
            arrays["fault_blocks"] = np.where(sign >= 0, 1, -1).astype(np.int8)
        return (
            "model",
            dict(
                grid=grid,
                backend=backend,
                fault=bool(p.get("fault")),
                zone_ids=np.unique(zones).tolist(),
                units={"coordinates": "m"},
                z_direction="up",
                horizontal_assumption=p["horizontal_assumption"],
                **extra,
            ),
            save_arrays(out, arrays),
        )
    if operation == "properties_assign":
        model = input_obj(request, "model")
        arrays = load_arrays(model)
        for name in ("phi", "ntg", "sw", "permeability_md", "kz_ratio"):
            arrays[name] = np.full(arrays["zones"].shape, np.nan)
        for zone, values in p["zones"].items():
            mask = arrays["zones"] == int(zone)
            for name, value in values.items():
                arrays[name][mask] = value
        numerics.validate_properties(arrays)
        return (
            "properties",
            dict(
                grid=grid_of(model),
                model_summary=model["summary"],
                backend="numpy-cpu",
                units={"phi": "fraction", "ntg": "fraction", "sw": "fraction", "permeability_md": "mD"},
                zones=p["zones"],
            ),
            save_arrays(out, arrays),
        )
    if operation == "volumetrics_calculate":
        props = input_obj(request, "properties")
        from opensubsurface.adapters.large_grid import evaluate, is_large

        if is_large(props):
            values = evaluate(props, [p])[0]
            summary = dict(
                values=values,
                units={k: "standard_m3" if k == "STOIIP" else "m3" for k in values},
                bo=p["bo"],
                contact_z_m=p["contact_z_m"],
                backend="cornerpoint-tetra6-cuda" if device == "cuda" else "chunked-cpu",
                precision="float64",
                storage=props["summary"]["storage"],
                block_cells=props["summary"]["block_cells"],
                assumptions=[
                    "Z up; horizontal OWC; static oil in place",
                    props["summary"].get("geometry_profile", "Uniform Cartesian cells"),
                ],
                vertical_cell_step_m=(
                    (grid_of(props)["extent"][5] - grid_of(props)["extent"][4]) / grid_of(props)["shape"][2]
                    if props["summary"]["storage"] == "cartesian-zarr-flat-v1"
                    else None
                ),
            )
        else:
            summary = numerics.volumes(
                load_arrays(props),
                grid_of(props),
                p["zone_ids"],
                p["contact_z_m"],
                p["bo"],
                device,
                p["execution"]["precision"],
            )
        (out / "result.json").write_text(
            json.dumps(summary, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        return "volumetrics", summary, {"result.json": out / "result.json"}
    if operation == "scenarios_run":
        props = input_obj(request, "properties")
        from opensubsurface.adapters.large_grid import evaluate, is_large

        large = is_large(props)
        arrays, grid = (None if large else load_arrays(props)), grid_of(props)
        rng = np.random.default_rng(p["seed"])
        samples = {}
        for name, distribution in p["distributions"].items():
            kind = distribution["kind"]
            if kind == "constant":
                values = np.repeat(distribution["low"], p["count"])
            elif kind == "uniform":
                values = rng.uniform(distribution["low"], distribution["high"], p["count"])
            else:
                values = rng.triangular(
                    distribution["low"], distribution["mode"], distribution["high"], p["count"]
                )
            if name in ("phi", "ntg", "sw"):
                require(((values >= 0) & (values <= 1)).all(), "QC_FAILED", f"{name} вне [0,1]")
            if name == "bo":
                require((values > 0).all(), "QC_FAILED", "Bo должен быть положительным")
            samples[name] = values
        rows, metrics = [], []
        if large:
            cases = []
            for i in range(p["count"]):
                row = {name: float(values[i]) for name, values in samples.items()}
                cases.append(
                    dict(
                        zone_ids=p["zone_ids"],
                        contact_z_m=row.get("contact_z_m", p["contact_z_m"]),
                        bo=row.get("bo", p["bo"]),
                        overrides=row,
                    )
                )
            computed = evaluate(props, cases)
            for i, result in enumerate(computed):
                rows.append(
                    dict(realization=i, seed=p["seed"], parameters=cases[i]["overrides"], result=result)
                )
                metrics.append(result["STOIIP"])
        for i in range(p["count"]):
            if large:
                break
            row = {name: float(values[i]) for name, values in samples.items()}
            realization = {k: v.copy() for k, v in arrays.items()}
            mask = np.isin(arrays["zones"], p["zone_ids"]) & arrays["active"]
            for key in ("phi", "ntg", "sw"):
                if key in row:
                    realization[key][mask] = row[key]
            result = numerics.volumes(
                realization,
                grid,
                p["zone_ids"],
                row.get("contact_z_m", p["contact_z_m"]),
                row.get("bo", p["bo"]),
                device,
            )
            rows.append(dict(realization=i, seed=p["seed"], parameters=row, result=result["values"]))
            metrics.append(result["values"]["STOIIP"])
        (out / "samples.json").write_text(json.dumps(rows, allow_nan=False), encoding="utf-8")
        return (
            "scenarios",
            dict(
                count=p["count"],
                seed=p["seed"],
                backend="chunked-cpu" if large else device,
                metric="STOIIP",
                unit="standard_m3",
                statistics=numerics.quantiles(metrics),
            ),
            {"samples.json": out / "samples.json"},
        )
    if operation == "seismic_generate":
        return seismic.generate(p, out)
    if operation == "seismic_import":
        return seismic.import_segy(Path(request["upload_path"]), p, out)
    if operation == "seismic_source_import":
        from opensubsurface.adapters.seismic_stream import import_source

        return import_source(request["source_context"], p, out)
    if operation in ("seismic_slice", "seismic_attribute"):
        obj = input_obj(request, "volume")
        store, group = seismic.open_volume(obj["paths"]["cube.zip"])
        try:
            if operation == "seismic_slice":
                axis = {"inline": 0, "crossline": 1, "sample": 2}[p["axis"]]
                section = seismic.read_section(group, axis, p["index"])
                np.save(out / "slice.npy", section, allow_pickle=False)
                return (
                    "seismic_slice",
                    dict(
                        axis=p["axis"],
                        index=p["index"],
                        shape=list(section.shape),
                        domain=obj["summary"]["domain"],
                        sample_unit=obj["summary"]["sample_unit"],
                    ),
                    {"slice.npy": out / "slice.npy"},
                )
            # Read complete traces per tile, never Hilbert over independent sample fragments.
            require(
                int(np.prod(group["amplitude"].shape)) <= 50_000_000,
                "UNSUPPORTED_LARGE_OPERATION",
                "Attributes currently require <=50M samples; large source import is separate",
            )
            target = out / "cube.zip"
            import zarr

            with zarr.ZipStore(str(target), mode="w") as dest:
                result_group = zarr.group(dest)
                shape = group["amplitude"].shape
                amplitude = result_group.create_dataset(
                    "amplitude", shape=shape, dtype="f8", chunks=(1, 1, shape[-1])
                )
                for i in range(shape[0]):
                    amplitude[i, :, :] = numerics.seismic_attribute(
                        group["amplitude"][i, :, :], p["attribute"], p["window"], device
                    )
                for key in ("inline", "crossline", "sample", "x", "y"):
                    result_group.create_dataset(key, data=group[key][:])
            summary = dict(obj["summary"])
            for key in ("amplitude_min", "amplitude_max", "amplitude_rms", "qc_status"):
                summary.pop(key, None)
            summary.update(
                attribute=p["attribute"],
                backend=device,
                dtype="float64",
                storage="seismic-attribute-f64-v1",
                chunks=[1, 1, shape[-1]],
                boundary="nearest" if p["attribute"] == "rms" else "periodic full trace FFT",
                mask_policy="Entire trace masked if any sample missing",
            )
            return "seismic", summary, {"cube.zip": target}
        finally:
            store.close()
    if operation == "interpretation_save":
        obj = input_obj(request, "volume")
        store, group = seismic.open_volume(obj["paths"]["cube.zip"])
        try:
            picks = []
            for pick in p["picks"]:
                require(
                    pick["inline"] in group["inline"][:] and pick["crossline"] in group["crossline"][:],
                    "QC_FAILED",
                    "Pick не соответствует geometry",
                )
                i = int(np.where(group["inline"][:] == pick["inline"])[0][0])
                j = int(np.where(group["crossline"][:] == pick["crossline"])[0][0])
                sample = pick["sample_index"]
                require(sample <= len(group["sample"]) - 1, "QC_FAILED", "Pick вне sample axis")
                value = float(np.interp(sample, np.arange(len(group["sample"])), group["sample"][:]))
                x, y = float(group["x"][i, j]), float(group["y"][i, j])
                require(np.isfinite([x, y, value]).all(), "QC_FAILED", "Pick на missing trace")
                picks.append(dict(**pick, x=x, y=y, value=value))
            (out / "picks.json").write_text(json.dumps(picks), encoding="utf-8")
            return (
                "interpretation",
                dict(
                    name=p["name"],
                    count=len(picks),
                    domain=obj["summary"]["domain"],
                    unit=obj["summary"]["sample_unit"],
                    extrapolation=False,
                    interpolation="none; original picks",
                    crs=obj["summary"]["crs"],
                    vertical_datum=obj["summary"]["vertical_datum"],
                ),
                {"picks.json": out / "picks.json"},
            )
        finally:
            store.close()
    if operation == "horizon_convert_domain":
        obj = input_obj(request, "interpretation")
        require(obj["summary"]["domain"] == "twt", "QC_FAILED", "Конвертировать можно только TWT picks")
        require(
            p["datum"] == obj["summary"]["vertical_datum"], "MISSING_DATUM", "Datum velocity не совпадает"
        )
        points = json.loads(Path(obj["paths"]["picks.json"]).read_text(encoding="utf-8"))

        def convert_time(value):
            if p.get("time_depth_table") is not None:
                return float(numerics.table_time_to_z(value, p["time_depth_table"], p["origin_z_m"]))
            return float(numerics.time_to_z(value, p["velocity_m_s"], p["origin_z_m"]))

        import csv

        with (out / "surfaces.csv").open("w") as f:
            writer = csv.DictWriter(f, fieldnames=["horizon", "x", "y", "z"])
            writer.writeheader()
            for pick in points:
                writer.writerow(
                    dict(
                        horizon=obj["summary"]["name"],
                        x=pick["x"],
                        y=pick["y"],
                        z=convert_time(pick["value"]),
                    )
                )
        table = __import__("pyarrow").Table.from_pylist(
            [
                dict(
                    horizon=obj["summary"]["name"],
                    x=pick["x"],
                    y=pick["y"],
                    z=convert_time(pick["value"]),
                )
                for pick in points
            ]
        )
        pq.write_table(table, out / "data.parquet")
        return (
            "dataset",
            dict(
                kind="surfaces",
                domain="depth",
                unit="m",
                crs=obj["summary"]["crs"],
                vertical_datum=p["datum"],
                assumption="1D piecewise linear table, no extrapolation"
                if p.get("time_depth_table")
                else "1D constant velocity; depth=v*TWT/2",
                time_depth_table=p.get("time_depth_table"),
                velocity_m_s=p["velocity_m_s"],
            ),
            {"data.parquet": out / "data.parquet", "surfaces.csv": out / "surfaces.csv"},
        )
    if operation in ("variogram_fit", "properties_krige", "properties_simulate"):
        props = input_obj(request, "properties")
        arrays, summary = geostat.conditioned(p, load_arrays(props), grid_of(props), operation)
        summary.update(grid=grid_of(props), model_summary=props["summary"].get("model_summary", {}))
        return "properties", summary, save_arrays(out, arrays)
    if operation == "simulation_case_create":
        props = input_obj(request, "properties")
        return opm.generate_case(
            p, load_arrays(props), grid_of(props), out, props["summary"].get("model_summary", {})
        )
    if operation == "simulation_snapshot":
        from opensubsurface.adapters.results import snapshot

        result = input_obj(request, "result")
        require("states.zip" in result["paths"], "INVALID_RESULTS", "Нет канонических restart snapshots")
        section, summary = snapshot(
            result["paths"]["states.zip"], p["report_index"], p["field"], p["axis"], p["index"]
        )
        np.save(out / "slice.npy", section, allow_pickle=False)
        summary["grid"] = result["summary"]["grid"]
        return "simulation_snapshot", summary, {"slice.npy": out / "slice.npy"}
    if operation == "simulation_deck_run":
        from opensubsurface.simulation.run import run_deck

        return run_deck(request, out)
    if operation == "simulation_submit":
        case = input_obj(request, "case")
        return opm.run_case(case["paths"], dict(p, _case_summary=case["summary"]), out)
    require(False, "UNSUPPORTED_OPERATION", "Операция не поддерживается вычислительным worker")
