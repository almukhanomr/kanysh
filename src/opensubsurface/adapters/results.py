"""Binary parsing is exclusively delegated to resdata. Canonical states retain the geological mapping."""

import csv

import numpy as np
import zarr

from opensubsurface.domain.numerics import from_opm
from opensubsurface.errors import DomainError, require


def write_series_csv(series, path):
    keys = list(series["vectors"])
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date_utc"] + [k + " [" + series["vectors"][k]["unit"] + "]" for k in keys])
        for i, date in enumerate(series["dates"]):
            writer.writerow([date] + [series["vectors"][k]["values"][i] for k in keys])


def read_restart_fields(directory, mapping_path, output):
    try:
        from resdata.grid import Grid
        from resdata.resfile import ResdataFile, ResdataRestartFile
    except ImportError:
        raise DomainError("RESULT_READER_UNAVAILABLE", "Установите extra solver (resdata)")
    with np.load(mapping_path, allow_pickle=False) as mapping:
        active = mapping["active"].astype(bool)
    shape = active.shape
    grid = Grid(str(directory / "CASE.EGRID"))
    require(
        tuple(grid.get_dims()[:3]) == shape, "GRID_MAPPING_ERROR", "EGRID dimensions не совпадают с геологией"
    )
    # This bridge is METRIC-only; imported FIELD grids require a separately validated profile.
    require(
        grid.unit_system.name == "METRIC", "INVALID_UNITS", "Restart reader этого bridge требует METRIC grid"
    )
    actual = from_opm(grid.export_actnum().numpy_copy(), shape).astype(bool)
    require(np.array_equal(actual, active), "GRID_MAPPING_ERROR", "EGRID ACTNUM не совпадает с GridMapping")
    init = ResdataFile(str(directory / "CASE.INIT"))
    require("PORV" in init, "INVALID_RESULTS", "INIT не содержит PORV")
    pore_volume = from_opm(init["PORV"][0].numpy_copy(), shape, active)
    require(
        np.isfinite(pore_volume[active]).all() and (pore_volume[active] > 0).all(),
        "INVALID_RESULTS",
        "Неположительный/неполный simulator PORV",
    )
    restart = ResdataRestartFile(grid, str(directory / "CASE.UNRST"))
    headers = restart.headers()
    require(bool(headers), "INCOMPLETE_OUTPUT", "Нет restart report snapshots")
    dates = []
    days = []
    reports = []
    fields = set()
    with zarr.ZipStore(str(output), mode="w") as store:
        group = zarr.group(store=store)
        group.create_dataset("active", data=active)
        group.create_dataset("pore_volume", data=pore_volume)
        for index, header in enumerate(headers):
            view = restart.restart_view(seqnum_index=index)
            from datetime import timezone

            date = header.get_sim_date()
            dates.append(date.replace(tzinfo=timezone.utc).isoformat())
            days.append(float(header.get_sim_days()))
            reports.append(int(header.get_report_step()))
            require(
                "PRESSURE" in view and "SWAT" in view,
                "INCOMPLETE_OUTPUT",
                "PRESSURE/SWAT отсутствуют в restart",
            )
            values = {}
            for keyword, name in [("PRESSURE", "pressure"), ("SWAT", "sw"), ("SGAS", "sg")]:
                if keyword in view:
                    array = from_opm(view[keyword][0].numpy_copy(), shape, active)
                    require(
                        np.isfinite(array[active]).all(), "INVALID_RESULTS", "NaN/Inf в restart " + keyword
                    )
                    values[name] = array
            values["so"] = 1 - values["sw"] - values.get("sg", 0)
            for name, array in values.items():
                if name in ("sw", "so", "sg"):
                    require(
                        ((array[active] >= -1e-6) & (array[active] <= 1 + 1e-6)).all(),
                        "INVALID_RESULTS",
                        "Насыщенность вне диапазона: " + name,
                    )
                if name not in fields:
                    group.create_dataset(
                        name,
                        shape=(len(headers), *shape),
                        dtype="f8",
                        chunks=(1, min(shape[0], 16), min(shape[1], 16), shape[2]),
                        fill_value=np.nan,
                    )
                    fields.add(name)
                group[name][index] = array
        require(
            all(a < b for a, b in zip(days, days[1:])),
            "INVALID_RESULTS",
            "Restart report times не возрастают",
        )
        group.attrs.update(
            dates=dates,
            elapsed_days=days,
            reports=reports,
            units=dict(pressure="bara", sw="fraction", so="fraction", sg="fraction"),
        )
    return dict(
        restart_dates=dates,
        restart_days=days,
        restart_reports=reports,
        fields=sorted(fields),
        simulator_pore_volume_m3=float(pore_volume[active].sum()),
    )


def snapshot(path, report_index, field, axis, index):
    with zarr.ZipStore(str(path), mode="r") as store:
        group = zarr.open_group(store, mode="r")
        require(field in group, "MISSING_VECTOR", "Поле не записано в simulation result: " + field)
        require(report_index < len(group.attrs["dates"]), "INVALID_ARGUMENTS", "Report index вне диапазона")
        dim = {"XY": 2, "XZ": 1, "YZ": 0}[axis]
        require(index < group[field].shape[dim + 1], "INVALID_ARGUMENTS", "Индекс среза вне сетки")
        selector = [report_index, slice(None), slice(None), slice(None)]
        selector[dim + 1] = index
        section = np.asarray(group[field][tuple(selector)])
        summary = dict(
            date=group.attrs["dates"][report_index],
            report_index=report_index,
            field=field,
            unit=group.attrs["units"][field],
            axis=axis,
            index=index,
            shape=list(section.shape),
        )
        return section, summary


def write_analysis_csv(analysis, path):
    vectors = list(analysis["pointwise"])
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        columns = ["date_utc"]
        for name in vectors:
            unit = analysis["pointwise"][name]["unit"]
            columns.extend(
                [
                    name + " " + suffix + " [" + unit + "]"
                    for suffix in ("Q10/P90", "Q50/P50", "Q90/P10", "sample_count")
                ]
            )
        writer.writerow(columns)
        for i, date in enumerate(analysis["dates"]):
            row = [date]
            for name in vectors:
                band = analysis["pointwise"][name]
                stat = band["statistics"][i]
                row.extend([stat[k] if stat else None for k in ("Q10", "Q50", "Q90")])
                row.append(band["sample_counts"][i])
            writer.writerow(row)


def conservation_report(states_path, initial_path, series, case):
    """Fresh dead-oil oil/water, constant FVF and incompressible rock only."""
    from copy import deepcopy
    from datetime import datetime, timezone

    from opensubsurface.domain.results import align_series, component_balance

    if (
        case.get("initialization_profile") != "fresh_explicit"
        or case.get("rock_compressibility_per_bar") != 0
    ):
        return dict(
            status="UNSUPPORTED_PROFILE",
            reason="Conservation adapter требует fresh explicit constant-PVT, incompressible rock",
        )
    required = {"FOPT", "FWPT", "FWIT"}
    if not required <= set(series["vectors"]):
        return dict(status="NOT RUN", reason="Не хватает component production/injection cumulative vectors")
    start = datetime.fromisoformat(case["start_date"]).replace(tzinfo=timezone.utc).isoformat()
    augmented = deepcopy(series)
    if augmented["dates"][0] > start:
        augmented["dates"].insert(0, start)
        if augmented.get("elapsed_days") is not None:
            augmented["elapsed_days"].insert(0, 0.0)
        for vector in augmented["vectors"].values():
            vector["values"].insert(0, 0.0 if vector["kind"] == "cumulative" else None)
    initial_cumul = align_series(augmented, [start])
    require(
        all(initial_cumul[name][0] is not None and abs(initial_cumul[name][0]) < 1e-10 for name in required),
        "UNSUPPORTED_CONSERVATION_PROFILE",
        "Fresh case должен начинаться с нулевых cumulative amounts",
    )
    with np.load(initial_path, allow_pickle=False) as initial:
        initial_sw = initial["sw"]
        initial_pressure = initial["pressure"]
        expected_pv = initial["pore_volume"]
    with zarr.ZipStore(str(states_path), mode="r") as store:
        group = zarr.open_group(store, mode="r")
        active = group["active"][:].astype(bool)
        pv = group["pore_volume"][:]
        baseline_oil = float(np.sum(pv[active] * (1 - initial_sw[active]) / case["bo"]))
        baseline_water = float(np.sum(pv[active] * initial_sw[active] / case["bw"]))
        dates = [start]
        oil = [baseline_oil]
        water = [baseline_water]
        pressure_drift = [0.0]
        for i, date in enumerate(group.attrs["dates"]):
            require(date >= start, "INVALID_RESULTS", "Restart предшествует start date")
            sw = group["sw"][i][active]
            pressure = group["pressure"][i][active]
            stocks = [
                float(np.sum(pv[active] * (1 - sw) / case["bo"])),
                float(np.sum(pv[active] * sw / case["bw"])),
            ]
            drift = float(
                np.max(np.abs(pressure - initial_pressure[active]))
                / max(float(np.max(np.abs(initial_pressure[active]))), 1.0)
            )
            if date == start:
                oil[0], water[0] = stocks
                pressure_drift[0] = drift
            else:
                dates.append(date)
                oil.append(stocks[0])
                water.append(stocks[1])
                pressure_drift.append(drift)
        actual_pv = float(np.sum(pv[active]))
        expected = float(np.sum(expected_pv[active]))
    aligned = align_series(augmented, dates)
    require(
        all(v is not None for name in required for v in aligned[name]),
        "INCOMPLETE_OUTPUT",
        "Нет summary coverage на restart dates; баланс не экстраполируется",
    )
    oil_balance = component_balance(oil, aligned["FOPT"], np.zeros(len(dates)), "standard_m3")
    water_balance = component_balance(water, aligned["FWPT"], aligned["FWIT"], "standard_m3")
    tolerance = 1e-6 if case["profile"] == "no_flow" else 1e-4
    pv_error = abs(actual_pv - expected) / max(abs(expected), 1.0)
    errors = []
    if pv_error > 1e-6:
        errors.append("INIT PORV не совпадает с экспортированным net-rock NTG convention")
    for name, balance in [("oil", oil_balance), ("water", water_balance)]:
        if balance["max_abs_normalized_residual"] > tolerance:
            errors.append("Component balance residual выше допуска: " + name)
    if case["profile"] == "no_flow" and max(pressure_drift) > 1e-6:
        errors.append("No-flow pressure drift выше допуска 1e-6")
    return dict(
        status="FAIL" if errors else "PASS",
        errors=errors,
        dates=dates,
        oil=oil_balance,
        water=water_balance,
        initial_oil_standard_m3=baseline_oil,
        initial_water_standard_m3=baseline_water,
        initial_porv_m3=actual_pv,
        expected_porv_m3=expected,
        porv_relative_error=pv_error,
        pressure_max_relative_drift=max(pressure_drift),
        component_relative_tolerance=tolerance,
        convention="Conserved dead-oil oil/water standard amounts, constant Bo/Bw; compressible cases unsupported",
    )
