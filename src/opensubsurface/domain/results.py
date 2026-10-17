"""Normalized, unit-aware report series and uncertainty. No simulated forecasts are generated here."""

from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import AwareDatetime, Field, model_validator

from opensubsurface.domain.numerics import quantiles, water_cut
from opensubsurface.errors import require
from opensubsurface.schemas import Strict

# Petroleum barrel and standard cubic foot conversions are exact dimensional conversions;
# thermodynamic standard conditions are compared separately, never inferred from a unit name.
STB_M3 = 0.158987294928
SCF_M3 = 0.028316846592
VECTOR_KINDS = {
    "FOPR": "rate",
    "FWPR": "rate",
    "FWIR": "rate",
    "FGPR": "rate",
    "FOPT": "cumulative",
    "FWPT": "cumulative",
    "FWIT": "cumulative",
    "FGPT": "cumulative",
    "FPR": "state",
    "WATER_CUT": "fraction",
}
CANONICAL_UNITS = {
    "rate": "standard_m3/day",
    "cumulative": "standard_m3",
    "state": "bara",
    "fraction": "fraction",
}


class StandardConditions(Strict):
    pressure_pa: float = Field(gt=0)
    temperature_k: float = Field(gt=0)


class Vector(Strict):
    values: list[float | None] = Field(min_length=1)
    unit: str
    kind: Literal["rate", "cumulative", "state", "fraction"]


class ReportSeries(Strict):
    schema_version: Literal[1] = 1
    dates: list[AwareDatetime] = Field(min_length=1)
    vectors: dict[str, Vector]
    standard_conditions: StandardConditions
    pressure_reference: Literal["absolute"] = "absolute"
    completed: bool
    elapsed_days: list[float] | None = None
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self):
        if any(a >= b for a, b in zip(self.dates, self.dates[1:])):
            raise ValueError("Календарные даты должны строго возрастать")
        if self.elapsed_days is not None and (
            len(self.elapsed_days) != len(self.dates)
            or any(a >= b for a, b in zip(self.elapsed_days, self.elapsed_days[1:]))
        ):
            raise ValueError("elapsed_days не соответствует календарным датам")
        if any(len(v.values) != len(self.dates) for v in self.vectors.values()):
            raise ValueError("Длина вектора не совпадает с датами")
        for name, vector in self.vectors.items():
            expected = "state" if name.startswith("WBHP:") else VECTOR_KINDS.get(name)
            if expected is None or expected != vector.kind:
                raise ValueError("Неизвестный вектор или неверный вид величины: " + name)
        return self


def utc_string(value):
    require(value.utcoffset() is not None, "INVALID_RESULTS", "Дата должна иметь явный timezone")
    return value.astimezone(timezone.utc).isoformat()


def conversion(unit, kind):
    aliases = unit.strip().upper().replace(" ", "")
    if unit == CANONICAL_UNITS[kind]:
        return 1.0
    factors = {
        "rate": {
            "SM3/DAY": 1.0,
            "SM3/D": 1.0,
            "STB/DAY": STB_M3,
            "STB/D": STB_M3,
            "MSCF/DAY": 1000 * SCF_M3,
            "MSCF/D": 1000 * SCF_M3,
        },
        "cumulative": {"SM3": 1.0, "STB": STB_M3, "MSCF": 1000 * SCF_M3},
        "state": {"BARSA": 1.0, "BARA": 1.0, "BAR": 1.0, "PSIA": 0.06894757293168, "PA": 1e-5, "KPA": 0.01},
        "fraction": {"FRACTION": 1.0, "1": 1.0, "%": 0.01},
    }
    require(aliases in factors[kind], "INVALID_UNITS", f"Не поддерживается единица {unit} для {kind}")
    return factors[kind][aliases]


def normalize_series(raw):
    series = ReportSeries.model_validate(raw)
    result = series.model_dump(mode="json")
    result["dates"] = [utc_string(d) for d in series.dates]
    for name, vector in series.vectors.items():
        factor = conversion(vector.unit, vector.kind)
        values = [None if v is None else float(v * factor) for v in vector.values]
        if vector.kind == "cumulative":
            adjacent = [(a, b) for a, b in zip(values, values[1:]) if a is not None and b is not None]
            require(
                all(b >= a - 1e-8 * max(abs(a), 1) for a, b in adjacent),
                "INVALID_RESULTS",
                "Накопленная добыча/закачка не должна убывать: " + name,
            )
        if vector.kind in ("rate", "cumulative", "fraction"):
            require(
                all(v is None or v >= 0 for v in values), "INVALID_RESULTS", "Отрицательное значение: " + name
            )
        if vector.kind == "fraction":
            require(all(v is None or v <= 1 for v in values), "INVALID_RESULTS", "Доля вне [0,1]")
        result["vectors"][name] = dict(values=values, unit=CANONICAL_UNITS[vector.kind], kind=vector.kind)
    if "FOPR" in result["vectors"] and "FWPR" in result["vectors"]:
        oil = np.array(result["vectors"]["FOPR"]["values"], dtype=float)
        water = np.array(result["vectors"]["FWPR"]["values"], dtype=float)
        values = water_cut(oil, water)
        result["vectors"]["WATER_CUT"] = dict(
            kind="fraction", unit="fraction", values=[float(v) if np.isfinite(v) else None for v in values]
        )
    return result


def timestamps(dates):
    return np.array([datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp() for d in dates])


def align_vector(series, name, dates):
    """Rates: left-constant; cumulative/state: linear adjacent samples; never bridge null gaps/extrapolate."""
    if name not in series["vectors"]:
        return [None] * len(dates)
    source = timestamps(series["dates"])
    target = timestamps(dates)
    vector = series["vectors"][name]
    values = np.array(vector["values"], dtype=float)
    out = np.full(len(target), np.nan)
    for n, t in enumerate(target):
        if t < source[0] or t > source[-1]:
            continue
        i = np.searchsorted(source, t, side="right") - 1
        if source[i] == t or vector["kind"] == "rate":
            out[n] = values[i]
        elif i + 1 < len(source) and np.isfinite(values[i : i + 2]).all():
            fraction = (t - source[i]) / (source[i + 1] - source[i])
            out[n] = values[i] + fraction * (values[i + 1] - values[i])
    return [float(v) if np.isfinite(v) else None for v in out]


def align_series(series, dates):
    result = {name: align_vector(series, name, dates) for name in series["vectors"] if name != "WATER_CUT"}
    if "FOPR" in result and "FWPR" in result:
        cut = water_cut(np.array(result["FOPR"], float), np.array(result["FWPR"], float))
        result["WATER_CUT"] = [float(v) if np.isfinite(v) else None for v in cut]
    return result


def analyze_cases(
    cases,
    metric="FOPT",
    dates=None,
    report_at=None,
    allow_partial=False,
    direction="maximize",
    constraints=None,
):
    """cases: explicit [{id,status,series?,error?}]; failed/incomplete cases remain in the report."""
    require(bool(cases), "INVALID_COMPARISON", "Нет явно выбранных cases")
    require(len({c["id"] for c in cases}) == len(cases), "INVALID_COMPARISON", "Дубли cases")
    excluded = []
    eligible = []
    for case in cases:
        if case["status"] != "succeeded" or case.get("series") is None:
            excluded.append(
                dict(id=case["id"], status=case["status"], reason=case.get("error", "Нет результата"))
            )
            continue
        series = normalize_series(case["series"])
        if not series["completed"]:
            excluded.append(dict(id=case["id"], status="incomplete", reason="Расчёт не завершил schedule"))
        else:
            eligible.append(dict(id=case["id"], series=series))
    require(
        allow_partial or not excluded,
        "PARTIAL_RESULTS",
        "Есть failed/incomplete cases; явно разрешите частичный отчёт",
    )
    require(bool(eligible), "NO_RESULTS", "Нет завершённых cases для статистики")
    standard = eligible[0]["series"]["standard_conditions"]
    require(
        all(c["series"]["standard_conditions"] == standard for c in eligible),
        "INVALID_COMPARISON",
        "Различаются стандартные условия объёмов; пересчёт условий не выполняется автоматически",
    )
    common_start = max(c["series"]["dates"][0] for c in eligible)
    common_end = min(c["series"]["dates"][-1] for c in eligible)
    require(common_start <= common_end, "INVALID_COMPARISON", "Нет общего календарного диапазона")
    if dates is None:
        dates = sorted({d for c in eligible for d in c["series"]["dates"] if common_start <= d <= common_end})
    else:
        dates = [utc_string(datetime.fromisoformat(d.replace("Z", "+00:00"))) for d in dates]
        require(
            all(a < b for a, b in zip(dates, dates[1:])),
            "INVALID_COMPARISON",
            "Даты сравнения должны возрастать",
        )
    report_at = (
        utc_string(datetime.fromisoformat(report_at.replace("Z", "+00:00"))) if report_at else common_end
    )
    vectors = sorted(set.intersection(*(set(c["series"]["vectors"]) for c in eligible)))
    require(metric in vectors, "MISSING_VECTOR", "Метрика отсутствует в одном из cases: " + metric)
    aligned = {c["id"]: align_series(c["series"], dates) for c in eligible}
    bands = {}
    for name in vectors:
        stats = []
        sample_counts = []
        for n in range(len(dates)):
            values = [aligned[c["id"]][name][n] for c in eligible if aligned[c["id"]][name][n] is not None]
            sample_counts.append(len(values))
            stats.append(quantiles(values) if values else None)
        bands[name] = dict(
            statistics=stats,
            sample_counts=sample_counts,
            unit=eligible[0]["series"]["vectors"][name]["unit"],
            interpretation="Pointwise quantiles; P50 curve may not be a physical realization",
        )
    ranking = []
    missing_metric = []
    for case in eligible:
        point = align_series(case["series"], [report_at])
        value = point[metric][0]
        if value is None:
            missing_metric.append(dict(id=case["id"], reason="Метрика не определена на выбранную дату"))
            continue
        violations = []
        for constraint in constraints or []:
            name = constraint["metric"]
            observed = point.get(name, [None])[0]
            actual_unit = case["series"]["vectors"].get(name, {}).get("unit")
            require(
                actual_unit == constraint["unit"],
                "INVALID_UNITS",
                "Единицы ограничения не совпадают с canonical metric",
            )
            if (
                observed is None
                or (constraint.get("minimum") is not None and observed < constraint["minimum"])
                or (constraint.get("maximum") is not None and observed > constraint["maximum"])
            ):
                violations.append(
                    dict(
                        metric=name,
                        value=observed,
                        minimum=constraint.get("minimum"),
                        maximum=constraint.get("maximum"),
                    )
                )
        ranking.append(dict(id=case["id"], value=value, feasible=not violations, violations=violations))
    require(
        allow_partial or not missing_metric,
        "PARTIAL_RESULTS",
        "Метрика не определена для всех cases на выбранную дату",
    )
    require(bool(ranking), "NO_RESULTS", "Нет определённых значений целевой метрики")
    ranking.sort(
        key=lambda row: (
            not row["feasible"],
            -row["value"] if direction == "maximize" else row["value"],
            row["id"],
        )
    )
    representative = min(
        ranking, key=lambda row: abs(row["value"] - np.median([r["value"] for r in ranking]))
    )
    return dict(
        schema_version=1,
        total=len(cases),
        completed=len(eligible),
        excluded=excluded,
        partial=bool(excluded or missing_metric),
        dates=dates,
        pointwise=bands,
        series=aligned,
        report_at=report_at,
        metric=metric,
        unit=eligible[0]["series"]["vectors"][metric]["unit"],
        statistics=quantiles([r["value"] for r in ranking]),
        ranking=ranking,
        missing_metric=missing_metric,
        representative_case=dict(
            id=representative["id"], criterion="Closest actual case to median terminal metric"
        ),
        interpolation=dict(
            rate="previous sample",
            cumulative="linear",
            state="linear",
            fraction="derived from aligned rates",
            extrapolation=False,
            null_gaps="not bridged",
        ),
        standard_conditions=standard,
        claim="Ранжирование явных вариантов; глобальный оптимум не заявляется",
    )


def component_balance(inventory, produced, injected, unit, absolute_floor=1.0):
    """Conserved component amount, all same standard-volume or mass convention, never mixed phase volumes."""
    require(
        unit in ("standard_m3", "kg"),
        "INVALID_UNITS",
        "Balance требует mass или conserved standard component amount",
    )
    stock, prod, inj = (np.asarray(v, float) for v in (inventory, produced, injected))
    require(
        stock.ndim == 1 and len(stock) > 0 and stock.shape == prod.shape == inj.shape,
        "INVALID_RESULTS",
        "Размеры component balance не совпадают",
    )
    require(
        np.isfinite([stock, prod, inj]).all()
        and np.all(stock >= 0)
        and np.all(prod >= 0)
        and np.all(inj >= 0),
        "INVALID_RESULTS",
        "Невалидные component amounts",
    )
    require(absolute_floor > 0, "INVALID_RESULTS", "Нужен положительный physical absolute floor")
    # Cumulatives may include a nonzero baseline: conservation uses deltas from the first report.
    p = prod - prod[0]
    i = inj - inj[0]
    residual = stock - stock[0] + p - i
    denominator = np.maximum.reduce(
        [np.full_like(stock, max(abs(stock[0]), absolute_floor)), np.abs(p), np.abs(i)]
    )
    normalized = residual / denominator
    return dict(
        unit=unit,
        residual=residual.tolist(),
        normalized_residual=normalized.tolist(),
        max_abs_normalized_residual=float(np.max(np.abs(normalized))),
        absolute_floor=absolute_floor,
        formula="(inventory(t)-inventory(0)+production_delta-injection_delta)/max(abs(initial),abs(prod_delta),abs(inj_delta),floor)",
    )
