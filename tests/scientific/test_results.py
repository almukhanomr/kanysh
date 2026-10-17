"""Analytical arrays are test fixtures, never app-generated forecasts."""

import numpy as np
import pytest

from opensubsurface.domain.results import (
    STB_M3,
    ReportSeries,
    align_series,
    analyze_cases,
    component_balance,
    normalize_series,
)
from opensubsurface.errors import DomainError

DATES = ["2026-01-01T00:00:00+00:00", "2026-01-03T00:00:00+00:00", "2026-01-05T00:00:00+00:00"]
STD = dict(pressure_pa=101325.0, temperature_k=288.71)


def series(multiplier=1):
    return dict(
        schema_version=1,
        dates=DATES,
        standard_conditions=STD,
        completed=True,
        provenance="Analytical unit-test fixture; not a reservoir simulation",
        vectors={
            "FOPT": dict(values=[0, 20 * multiplier, 60 * multiplier], unit="SM3", kind="cumulative"),
            "FOPR": dict(values=[0, 10 * multiplier, 20 * multiplier], unit="SM3/DAY", kind="rate"),
            "FWPR": dict(values=[0, 10 * multiplier, 20 * multiplier], unit="SM3/DAY", kind="rate"),
        },
    )


def test_units_rates_and_cumulatives_have_different_alignment_no_extrapolation():
    raw = series()
    raw["vectors"]["FOPT"].update(values=[0, 20 / STB_M3, 60 / STB_M3], unit="STB")
    normalized = normalize_series(raw)
    assert normalized["vectors"]["FOPT"]["values"] == pytest.approx([0, 20, 60])
    assert normalized["vectors"]["WATER_CUT"]["values"] == [None, 0.5, 0.5]
    dates = [
        "2025-12-31T00:00:00+00:00",
        "2026-01-02T00:00:00+00:00",
        "2026-01-04T00:00:00+00:00",
        "2026-01-06T00:00:00+00:00",
    ]
    aligned = align_series(normalized, dates)
    assert aligned["FOPT"] == [None, 10, 40, None]
    assert aligned["FOPR"] == [None, 0, 10, None]
    assert aligned["WATER_CUT"] == [None, None, 0.5, None]


def test_null_gap_not_bridged_and_actual_calendar_dates_matter():
    raw = series()
    raw["vectors"]["FOPT"]["values"][1] = None
    normalized = normalize_series(raw)
    aligned = align_series(normalized, ["2026-01-02T00:00:00+00:00", "2026-01-03T00:00:00+00:00"])
    assert aligned["FOPT"] == [None, None]
    later = series()
    later["dates"] = [d.replace("2026-01", "2026-02") for d in DATES]
    with pytest.raises(DomainError, match="календарного"):
        analyze_cases(
            [
                dict(id="a", status="succeeded", series=series()),
                dict(id="b", status="succeeded", series=later),
            ]
        )


def test_pointwise_quantiles_partial_counting_and_representative_is_real_case():
    cases = [dict(id=str(i), status="succeeded", series=series(m)) for i, m in enumerate([1, 2, 3])]
    cases.append(dict(id="failed-4", status="failed", error=dict(code="COMPUTE_FAILED")))
    with pytest.raises(DomainError, match="частичный"):
        analyze_cases(cases)
    result = analyze_cases(cases, allow_partial=True)
    assert result["completed"] == 3 and result["total"] == 4 and result["partial"]
    assert result["excluded"][0]["id"] == "failed-4"
    stats = result["pointwise"]["FOPT"]["statistics"][-1]
    assert stats["P90"] == stats["Q10"] == pytest.approx(72.0)
    assert stats["P50"] == 120 and stats["P10"] == pytest.approx(168.0)
    assert result["pointwise"]["FOPT"]["sample_counts"] == [3, 3, 3]
    assert result["representative_case"]["id"] == "1"
    assert result["ranking"][0]["id"] == "2"


def test_no_silent_extrapolated_terminal_metric_or_incompatible_conditions():
    cases = [dict(id="a", status="succeeded", series=series())]
    with pytest.raises(DomainError, match="Метрика"):
        analyze_cases(cases, report_at="2026-01-06T00:00:00+00:00")
    changed = series()
    changed["standard_conditions"] = dict(pressure_pa=100000, temperature_k=288.71)
    with pytest.raises(DomainError, match="стандартные условия"):
        analyze_cases(cases + [dict(id="b", status="succeeded", series=changed)])
    with pytest.raises(ValueError):
        ReportSeries.model_validate(dict(series(), dates=["2026-01-01", "2026-01-03", "2026-01-05"]))


def test_bounded_ranking_constraints_and_units_are_explicit():
    cases = [
        dict(id="a", status="succeeded", series=series(1)),
        dict(id="b", status="succeeded", series=series(2)),
    ]
    result = analyze_cases(cases, constraints=[dict(metric="FOPT", unit="standard_m3", maximum=100)])
    assert result["ranking"][0]["id"] == "a" and result["ranking"][0]["feasible"]
    assert not result["ranking"][1]["feasible"]
    with pytest.raises(DomainError, match="Единицы"):
        analyze_cases(cases, constraints=[dict(metric="FOPT", unit="STB", maximum=100)])


def test_component_conservation_uses_component_amounts_and_initial_denominator():
    # Initial component inventory 1000; net injection10, production50 -> final960.
    balance = component_balance([1000, 980, 960], [0, 25, 50], [0, 5, 10], "standard_m3")
    assert balance["max_abs_normalized_residual"] == 0
    changed = component_balance([1000, 980, 961], [0, 25, 50], [0, 5, 10], "standard_m3")
    assert changed["normalized_residual"][-1] == pytest.approx(0.001)
    # Nonzero summary baseline must cancel, rather than double count prior production.
    assert component_balance([1000, 960], [80, 130], [10, 20], "kg")["max_abs_normalized_residual"] == 0
    with pytest.raises(DomainError, match="Balance"):
        component_balance([1000, 960], [0, 50], [0, 10], "reservoir_m3")


def test_failed_and_incomplete_are_explicit_and_never_used_as_completed_curves():
    partial = series()
    partial["completed"] = False
    cases = [
        dict(id="a", status="succeeded", series=series()),
        dict(id="incomplete", status="succeeded", series=partial),
    ]
    report = analyze_cases(cases, allow_partial=True)
    assert report["total"] == 2 and report["completed"] == 1
    assert report["excluded"][0]["status"] == "incomplete"


def test_closed_waterflood_component_report_rejects_a_real_inventory_mismatch(tmp_path):
    import zarr

    from opensubsurface.adapters.results import conservation_report

    path = tmp_path / "states.zip"
    shape = (1, 1, 1)
    with zarr.ZipStore(str(path), mode="w") as store:
        group = zarr.group(store=store)
        group.create_dataset("active", data=np.ones(shape, bool))
        group.create_dataset("pore_volume", data=np.full(shape, 1000.0))
        group.create_dataset("sw", data=np.array([0.25, 0.4]).reshape(2, *shape))
        group.create_dataset("pressure", data=np.full((2, *shape), 200.0))
        group.attrs.update(dates=["2026-01-01T00:00:00+00:00", "2026-01-03T00:00:00+00:00"])
    np.savez(
        tmp_path / "initial.npz",
        sw=np.full(shape, 0.25),
        pressure=np.full(shape, 200.0),
        pore_volume=np.full(shape, 1000.0),
    )
    raw = series()
    raw["dates"] = raw["dates"][:2]
    raw["vectors"] = {
        "FOPT": dict(values=[0, 125], unit="SM3", kind="cumulative"),
        "FWPT": dict(values=[0, 10], unit="SM3", kind="cumulative"),
        "FWIT": dict(values=[0, 160], unit="SM3", kind="cumulative"),
    }
    case = dict(
        initialization_profile="fresh_explicit",
        rock_compressibility_per_bar=0,
        start_date="2026-01-01",
        bo=1.2,
        bw=1.0,
        profile="waterflood",
    )
    report = conservation_report(path, tmp_path / "initial.npz", normalize_series(raw), case)
    assert report["status"] == "PASS"
    assert report["oil"]["max_abs_normalized_residual"] < 1e-12
    raw["vectors"]["FOPT"]["values"][-1] = 100
    wrong = conservation_report(path, tmp_path / "initial.npz", normalize_series(raw), case)
    assert wrong["status"] == "FAIL" and wrong["errors"]
    assert (
        conservation_report(
            path,
            tmp_path / "initial.npz",
            normalize_series(raw),
            dict(case, rock_compressibility_per_bar=0.001),
        )["status"]
        == "UNSUPPORTED_PROFILE"
    )
