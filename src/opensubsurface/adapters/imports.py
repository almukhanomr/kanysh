import csv
from datetime import date

import numpy as np
import pint
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import CRS

from opensubsurface.errors import require

ureg = pint.UnitRegistry()
REQUIRED = {
    "collars": ["well_id", "x", "y", "reference_elevation"],
    "trajectory": ["well_id", "md", "x", "y", "z"],
    "markers": ["well_id", "horizon", "md"],
    "surfaces": ["horizon", "x", "y", "z"],
    "orientations": ["horizon", "x", "y", "z", "nx", "ny", "nz"],
    "production": ["well_id", "date", "oil_rate", "water_rate", "gas_rate", "pressure"],
}


def check_coordinates(crs, datum):
    require(
        bool(datum.strip()) and datum.lower() not in ("unknown", "неизвестно"),
        "MISSING_DATUM",
        "Укажите вертикальный datum",
    )
    if crs != "LOCAL_METRIC":
        parsed = CRS.from_user_input(crs)
        require(parsed.is_projected, "INVALID_CRS", "Нужна проекционная CRS с метрическими координатами")
        require(
            all(a.unit_name == "metre" for a in parsed.axis_info[:2]),
            "INVALID_CRS",
            "Координатные оси CRS должны быть в метрах",
        )


def import_dataset(path, p, out, context=None):
    check_coordinates(p["crs"], p["vertical_datum"])
    if p["kind"] == "las":
        import lasio

        require(bool(p["well_id"]), "QC_FAILED", "LAS требует явный well_id")
        las = lasio.read(str(path))
        require(float(las.version.VERS.value) in (1.2, 2.0), "UNSUPPORTED_PROFILE", "LAS только 1.2/2.0")
        data = {}
        units = {}
        for curve in las.curves:
            data[curve.mnemonic] = np.asarray(las[curve.mnemonic], float)
            units[curve.mnemonic] = p["units"].get(curve.mnemonic, curve.unit)
            require(bool(units[curve.mnemonic]), "INVALID_UNITS", f"Нет единиц кривой {curve.mnemonic}")
        depth = data[las.curves[0].mnemonic]
        depth_unit = units[las.curves[0].mnemonic]
        try:
            depth = (depth * ureg(depth_unit)).to("meter").magnitude
        except Exception:
            require(False, "INVALID_UNITS", "MD должен иметь единицу длины")
        require(
            np.isfinite(depth).all() and (np.diff(depth) > 0).all(),
            "QC_FAILED",
            "LAS MD должен строго возрастать",
        )
        data[las.curves[0].mnemonic] = depth
        units[las.curves[0].mnemonic] = "m"
        table = pa.table(data)
        summary = dict(
            kind="las",
            rows=len(depth),
            well_id=p["well_id"],
            units=units,
            null_fraction={k: float(np.isnan(v).mean()) for k, v in data.items()},
        )
    else:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            require(
                set(REQUIRED[p["kind"]]) <= set(reader.fieldnames or []),
                "QC_FAILED",
                "Не хватает обязательных CSV columns",
                remediation=", ".join(REQUIRED[p["kind"]]),
            )
            rows = list(reader)
        require(0 < len(rows) <= 1_000_000, "QC_FAILED", "Пустой или слишком большой CSV")
        if p["kind"] == "production":
            require(
                p.get("pressure_reference") == "absolute" and p.get("rate_reference") == "standard",
                "INVALID_UNITS",
                "Production требует absolute pressure и standard rates",
            )
            last_dates = {}
            for row in rows:
                try:
                    dt = date.fromisoformat(row["date"])
                except ValueError:
                    require(False, "QC_FAILED", "Дата должна быть ISO YYYY-MM-DD")
                require(
                    dt > last_dates.get(row["well_id"], date.min),
                    "QC_FAILED",
                    "Даты production должны возрастать",
                )
                last_dates[row["well_id"]] = dt
        string_fields = {"well_id", "horizon", "date"}
        numeric = [k for k in REQUIRED[p["kind"]] if k not in string_fields]
        for key in numeric:
            values = []
            unit = p["units"].get(key)
            is_length = key in ("x", "y", "z", "md", "reference_elevation")
            require(unit is not None or key in ("nx", "ny", "nz"), "INVALID_UNITS", f"Нет единицы {key}")
            try:
                factor = ureg(unit).to("m").magnitude if is_length else 1
                if key.endswith("_rate"):
                    factor = ureg(unit).to("m**3/day").magnitude
                if key == "pressure":
                    factor = ureg(unit).to("bar").magnitude
                for i, row in enumerate(rows):
                    value = float(row[key]) * factor
                    require(np.isfinite(value), "QC_FAILED", f"NaN/Inf: строка {i + 2}, {key}")
                    values.append(value)
            except (ValueError, pint.errors.PintError, TypeError):
                require(False, "INVALID_UNITS", f"Некорректное значение или units: {key}")
            for row, value in zip(rows, values):
                row[key] = value
        if p["kind"] == "production":
            require(
                all(row[k] >= 0 for row in rows for k in ("oil_rate", "water_rate", "gas_rate", "pressure")),
                "QC_FAILED",
                "Отрицательные production rates/absolute pressure",
            )
        if p["kind"] == "trajectory":
            last = {}
            for row in rows:
                require(
                    row["md"] > last.get(row["well_id"], -np.inf),
                    "QC_FAILED",
                    "MD должен строго возрастать в каждой скважине",
                )
                require(row["md"] >= 0, "QC_FAILED", "MD должен быть неотрицательным")
                last[row["well_id"]] = row["md"]
        if p["kind"] == "collars":
            require(len({r["well_id"] for r in rows}) == len(rows), "QC_FAILED", "Дубли well_id")
        if p["kind"] == "orientations":
            normals = np.array([[r["nx"], r["ny"], r["nz"]] for r in rows])
            require(
                np.allclose(np.linalg.norm(normals, axis=1), 1, atol=1e-5),
                "QC_FAILED",
                "Нормали должны быть единичными",
            )
        table = pa.Table.from_pylist([{k: r[k] for k in REQUIRED[p["kind"]]} for r in rows])
        summary = dict(
            kind=p["kind"],
            rows=len(rows),
            units={
                **p["units"],
                **{k: "m" for k in numeric if k in ("x", "y", "z", "md", "reference_elevation")},
            },
        )
    if p["kind"] == "production":
        summary["units"].update(oil_rate="m3/day", water_rate="m3/day", gas_rate="m3/day", pressure="bar")
        summary.update(pressure_reference="absolute", rate_reference="standard")
    if context is not None and p["kind"] in ("las", "trajectory", "markers", "production"):
        collars, trajectories = {}, {}
        for obj in context:
            kind = obj["summary"].get("kind")
            if kind not in ("collars", "trajectory"):
                continue
            for row in pq.read_table(obj["paths"]["data.parquet"]).to_pylist():
                if kind == "collars":
                    collars[row["well_id"]] = row
                else:
                    trajectories.setdefault(row["well_id"], []).append(row)
        ids = {p["well_id"]} if p["kind"] == "las" else set(table.column("well_id").to_pylist())
        known = set(collars) | (set(trajectories) if p["kind"] == "las" else set())
        require(
            ids <= known,
            "UNKNOWN_WELL",
            "Import collars, or an explicit XYZ/MD trajectory for LAS, before well-linked data",
        )
        if p["kind"] == "markers":
            normalized = []
            for row in table.to_pylist():
                track = sorted(trajectories.get(row["well_id"], []), key=lambda r: r["md"])
                require(bool(track), "QC_FAILED", "Marker требует XYZ/MD trajectory")
                md = np.array([r["md"] for r in track])
                require(
                    md[0] <= row["md"] <= md[-1],
                    "QC_FAILED",
                    "Marker MD вне trajectory; extrapolation запрещена",
                )
                row.update(
                    {k: float(np.interp(row["md"], md, [r[k] for r in track])) for k in ("x", "y", "z")}
                )
                normalized.append(row)
            table = pa.Table.from_pylist(normalized)
            summary["units"].update(x="m", y="m", z="m")
    pq.write_table(table, out / "data.parquet")
    summary.update(
        crs=p["crs"],
        vertical_datum=p["vertical_datum"],
        qc=[
            dict(
                code="VALIDATED",
                severity="info",
                object=p["kind"],
                row=None,
                message="Схема, конечность и базовые диапазоны проверены",
                suggested_action=None,
            )
        ],
    )
    return "dataset", summary, {"data.parquet": out / "data.parquet"}
