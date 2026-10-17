"""Explicit regional tornado and correlated marginal Monte Carlo; all runs are checked."""

import copy
import csv
import math

import numpy as np
from pydantic import ValidationError
from scipy import stats

from opensubsurface.adapters.regional_volumes import evaluate
from opensubsurface.errors import DomainError, require
from opensubsurface.schemas import RegionCase


def variant(p, parameters, values):
    value = copy.deepcopy(p)
    cases = {r["region_id"]: r for r in value["scenarios"][0]["regions"]}
    for parameter, number in zip(parameters, values):
        case = cases[parameter["region_id"]]
        name = parameter["field"]
        if name in {"phi", "ntg", "sw"}:
            key = name + ("_override" if parameter["mode"] == "scalar_override" else "_multiplier")
            if parameter["mode"] == "multiplier":
                number *= case.get(key) if case.get(key) is not None else 1.0
            if name == "sw" and parameter["mode"] == "scalar_override":
                require(
                    case.get("sw_height") is None,
                    "INVALID_ARGUMENTS",
                    "Cannot override a height function without explicitly changing the baseline model",
                )
            case[key] = float(number)
        else:
            require(case.get(name) is not None, "MISSING_PARAMETER", "Baseline parameter missing: " + name)
            case[name] = float(number) * (case[name] if parameter["mode"] == "multiplier" else 1.0)
        try:
            RegionCase.model_validate(case)
        except ValidationError as error:
            raise DomainError(
                "INVALID_SCENARIO", "Sample violates explicit phase/contact/property constraints"
            ) from error
    return value


def metric(result, name):
    value = result["tables"]["scenarios"][0].get(name)
    require(
        value is not None and np.isfinite(value),
        "MISSING_METRIC",
        "Requested metric is not calculated: " + name,
    )
    return float(value)


def budget(obj, p, runs):
    work = math.prod(obj["summary"]["grid"]["shape"]) * runs
    require(
        work <= p["max_cell_scenario_evaluations"],
        "COMPUTE_BUDGET_EXCEEDED",
        f"Requested {work} cell-scenario evaluations; reduce runs or explicitly raise the computation budget",
    )
    return work


def tornado(obj, p, out, polygon=None):
    work = budget(obj, p, 1 + 2 * len(p["parameters"]))
    base = evaluate(obj, p, polygon)
    baseline = metric(base, p["metric"])
    rows, failures = [], []
    for parameter in p["parameters"]:
        values = {}
        row = dict(
            parameter=f"{parameter['region_id']}.{parameter['field']}",
            mode=parameter["mode"],
            input_low=parameter["low"],
            input_high=parameter["high"],
            baseline=baseline,
        )
        for side in ("low", "high"):
            try:
                result = evaluate(obj, variant(p, [parameter], [parameter[side]]), polygon)
                values[side] = metric(result, p["metric"])
            except DomainError as error:
                values[side] = None
                failures.append(dict(parameter=row["parameter"], side=side, error=error.as_dict()))
        row.update(
            metric_low=values["low"],
            metric_high=values["high"],
            delta_low=values["low"] - baseline if values["low"] is not None else None,
            delta_high=values["high"] - baseline if values["high"] is not None else None,
        )
        row["swing"] = (
            abs(values["high"] - values["low"]) if all(v is not None for v in values.values()) else None
        )
        rows.append(row)
    rows.sort(key=lambda row: row["swing"] if row["swing"] is not None else -1, reverse=True)
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots(figsize=(10, max(3, len(rows) * 0.4 + 1)))
    for i, row in enumerate(rows):
        if row["swing"] is not None:
            low, high = sorted((row["metric_low"], row["metric_high"]))
            ax.barh(i, high - low, left=low, color="#208c98")
    ax.set_yticks(range(len(rows)), [r["parameter"] for r in rows])
    ax.invert_yaxis()
    ax.axvline(baseline, color="#cb6636", label="Baseline")
    ax.set_xlabel(p["metric"] + " (standard m³)")
    ax.set_title("One-at-a-time sensitivity; explicit user ranges")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "tornado.png", dpi=150)
    plt.close(fig)
    base.update(
        operation="sensitivity_tornado",
        status="FAIL"
        if any(f["error"]["code"] == "VALIDATION_FAILED" for f in failures)
        else "PARTIAL"
        if failures
        else "PASS",
        validation_status="FAIL"
        if any(f["error"]["code"] == "VALIDATION_FAILED" for f in failures)
        else "INCOMPLETE"
        if failures
        else "PASS",
        failures=failures,
        cell_scenario_evaluations=work,
        metric=p["metric"],
        parameters=p,
    )
    base["tables"]["tornado"] = rows
    base["limitations"].append(
        "One-at-a-time tornado ranges have no inferred probabilities and do not capture interactions"
    )
    return base


def draws(p):
    correlation = np.asarray(p["correlation"], float)
    n = len(p["parameters"])
    require(
        correlation.shape == (n, n)
        and np.isfinite(correlation).all()
        and np.allclose(correlation, correlation.T, rtol=0, atol=1e-12)
        and np.allclose(np.diag(correlation), 1, rtol=0, atol=1e-12)
        and (np.abs(correlation) <= 1 + 1e-12).all(),
        "INVALID_CORRELATION",
        "Finite symmetric unit-diagonal correlation matrix required",
    )
    eigen, vectors = np.linalg.eigh(correlation)
    require(eigen.min() >= -1e-10, "INVALID_CORRELATION", "Correlation matrix is not positive semidefinite")
    root = vectors @ np.diag(np.sqrt(np.maximum(eigen, 0)))
    normal = np.random.default_rng(p["seed"]).standard_normal((p["samples"], n)) @ root.T
    u = stats.norm.cdf(normal)
    values = np.empty_like(u)
    for i, parameter in enumerate(p["parameters"]):
        lo, hi = parameter["low"], parameter["high"]
        distribution = parameter["distribution"]
        if distribution == "uniform":
            values[:, i] = lo + (hi - lo) * u[:, i]
        elif distribution == "triangular":
            values[:, i] = stats.triang.ppf(
                u[:, i], (parameter["mode_value"] - lo) / (hi - lo), loc=lo, scale=hi - lo
            )
        elif distribution == "truncated_normal":
            mean, sigma = parameter["mean"], parameter["stddev"]
            values[:, i] = stats.truncnorm.ppf(
                u[:, i], (lo - mean) / sigma, (hi - mean) / sigma, loc=mean, scale=sigma
            )
        else:
            distribution = stats.lognorm(s=parameter["stddev_log"], scale=math.exp(parameter["mean_log"]))
            lower, upper = distribution.cdf([lo, hi])
            require(
                upper > lower,
                "INVALID_DISTRIBUTION",
                "Truncated lognormal has numerically empty probability mass",
            )
            values[:, i] = distribution.ppf(lower + (upper - lower) * u[:, i])
    require(np.isfinite(values).all(), "INVALID_DISTRIBUTION", "Nonfinite marginal samples")
    return values


def monte_carlo(obj, p, out, polygon=None):
    work = budget(obj, p, 1 + p["samples"])
    values = draws(p)
    base = evaluate(obj, p, polygon)
    baseline = metric(base, p["metric"])
    results, failures = [], []
    names = [f"{r['region_id']}.{r['field']}" for r in p["parameters"]]
    with (out / "mc_samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["sample", "status", *names, p["metric"], "error"])
        writer.writeheader()
        for index, row in enumerate(values):
            record = dict(sample=index, **dict(zip(names, map(float, row))))
            try:
                result = evaluate(obj, variant(p, p["parameters"], row), polygon)
                number = metric(result, p["metric"])
                results.append(number)
                record.update(status="PASS", **{p["metric"]: number})
            except DomainError as error:
                record.update(status="FAIL", error=error.code)
                failures.append(dict(sample=index, error=error.as_dict()))
            writer.writerow(record)
    if not results:
        base.update(
            operation="uncertainty_monte_carlo",
            status="FAIL",
            validation_status="FAIL"
            if any(f["error"]["code"] == "VALIDATION_FAILED" for f in failures)
            else "NOT RUN",
            parameters=p,
            attempted=p["samples"],
            valid_samples=0,
            failed_samples=len(failures),
            failures=failures[:100],
            scope="No valid realizations; no uncertainty percentiles calculated",
        )
        base["tables"]["percentiles"] = []
        return base
    sorted_values = sorted(results)
    stats_rows = []
    for label, q in (("P90", 0.1), ("P50", 0.5), ("P10", 0.9)):
        value = float(np.quantile(results, q, method="linear"))
        location = (len(results) - 1) * q
        left, right = math.floor(location), math.ceil(location)
        fraction = location - left
        reference = math.fsum((sorted_values[left] * (1 - fraction), sorted_values[right] * fraction))
        require(
            math.isclose(value, reference, rel_tol=1e-12, abs_tol=1e-9),
            "VALIDATION_FAILED",
            "Independent linear-rank quantile differs",
        )
        stats_rows.append(
            dict(percentile=label, quantile=q, metric=p["metric"], value=value, unit="standard_m3")
        )
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(sorted_values, np.linspace(100, 0, len(results)), color="#208c98")
    ax.set_xlabel(p["metric"] + " (standard m³)")
    ax.set_ylabel("Exceedance probability (%)")
    ax.set_title("S-curve; P90=Q10, P50=Q50, P10=Q90")
    for row in stats_rows:
        ax.axvline(row["value"], alpha=0.3, label=row["percentile"])
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "s_curve.png", dpi=150)
    plt.close(fig)
    empirical = np.corrcoef(values, rowvar=False) if len(names) > 1 else np.array([[1.0]])
    base.update(
        operation="uncertainty_monte_carlo",
        status="FAIL"
        if any(f["error"]["code"] == "VALIDATION_FAILED" for f in failures)
        else "PARTIAL"
        if failures
        else "PASS",
        validation_status="FAIL"
        if any(f["error"]["code"] == "VALIDATION_FAILED" for f in failures)
        else "INCOMPLETE"
        if failures
        else "PASS",
        parameters=p,
        metric=p["metric"],
        seed=p["seed"],
        attempted=p["samples"],
        valid_samples=len(results),
        failed_samples=len(failures),
        failures=failures[:100],
        baseline=baseline,
        cell_scenario_evaluations=work,
        correlation_space="Gaussian copula latent normal correlation; marginal Pearson correlation generally differs",
        empirical_marginal_pearson=[[float(v) if np.isfinite(v) else None for v in row] for row in empirical],
        quantile_convention="Linear rank/type 7; P90=Q10, P50=Q50, P10=Q90; conditional on valid realizations if any fail",
    )
    base["tables"]["percentiles"] = stats_rows
    base["independent_checks"].extend(
        [
            dict(name="all_valid_realizations_independent_hull_integrals", status="PASS", count=len(results)),
            dict(name="numpy_quantiles_vs_scalar_rank_interpolation", status="PASS"),
        ]
    )
    base["limitations"].extend(
        [
            "Regional scalar overrides/multipliers are not spatial geostatistical realizations",
            "All attempted draws are recorded; invalid physical draws are not resampled and yield a PARTIAL result",
            "Gaussian-copula correlations are explicit latent correlations, not a promise of exact finite-sample marginal Pearson correlations",
        ]
    )
    return base
