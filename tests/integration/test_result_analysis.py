import json

import pytest

from opensubsurface.errors import DomainError
from opensubsurface.schemas import DevelopmentRank
from opensubsurface.service import ref


def publish_result(service, pid, tmp_path, multiplier):
    raw = dict(
        schema_version=1,
        dates=["2026-01-01T00:00:00+00:00", "2026-01-03T00:00:00+00:00"],
        standard_conditions=dict(pressure_pa=101325.0, temperature_k=288.71),
        completed=True,
        provenance="Explicit analytical test fixture; not a simulator output",
        vectors={
            "FOPT": dict(values=[0, 20 * multiplier], unit="SM3", kind="cumulative"),
            "FOPR": dict(values=[0, 10 * multiplier], unit="SM3/DAY", kind="rate"),
            "FWPR": dict(values=[0, 5 * multiplier], unit="SM3/DAY", kind="rate"),
        },
    )
    path = tmp_path / ("series-" + str(multiplier) + ".json")
    path.write_text(json.dumps(raw))
    return service.store.publish(pid, "simulation_result", dict(final_day=2), {"series.json": path})


def test_service_normalizes_compares_and_exports_without_claiming_solver(service, tmp_path):
    project = service.invoke("project_create", dict(name="Analysis", vertical_datum="TEST"))
    pid = project["id"]
    a = publish_result(service, pid, tmp_path, 1)
    b = publish_result(service, pid, tmp_path, 2)
    comparison = service.invoke("simulation_compare", dict(project_id=pid, results=[ref(a), ref(b)]))
    assert comparison["summary"]["statistics"]["Q50"] == 30
    assert "analysis.json" in comparison["files"] and "analysis.csv" in comparison["files"]
    saved = json.loads(service.store.path(comparison, "analysis.json").read_text())
    assert saved["pointwise"]["FOPT"]["sample_counts"] == [2, 2]
    assert comparison["summary"]["report_date_count"] == 2
    assert "series" not in comparison["summary"]
    assert "Q10/P90" in service.store.path(comparison, "analysis.csv").read_text()
    rank = service.invoke(
        "development_rank",
        dict(
            project_id=pid,
            results=[ref(a), ref(b)],
            constraints=[dict(metric="FOPT", unit="standard_m3", maximum=30)],
        ),
    )
    assert rank["summary"]["ranking"][0]["id"].startswith(a["id"])
    assert rank["summary"]["ranking"][0]["feasible"]


def test_ensemble_failed_members_are_never_silently_dropped(service, tmp_path):
    project = service.invoke("project_create", dict(name="Partial", vertical_datum="TEST"))
    pid = project["id"]
    result = publish_result(service, pid, tmp_path, 1)
    ensemble = service.store.publish(
        pid,
        "ensemble",
        dict(
            total=2,
            completed=1,
            rows=[
                dict(status="succeeded", job_id="job-1", result=ref(result)),
                dict(status="failed", job_id="job-2", error=dict(code="COMPUTE_FAILED")),
            ],
        ),
    )
    with pytest.raises(DomainError, match="partial report"):
        service.invoke("ensemble_compare", dict(project_id=pid, ensemble=ref(ensemble)))
    comparison = service.invoke(
        "ensemble_compare", dict(project_id=pid, ensemble=ref(ensemble), allow_partial=True)
    )
    assert comparison["summary"]["completed"] == 1 and comparison["summary"]["total"] == 2
    assert comparison["summary"]["excluded"][0]["id"] == "job-2"


def test_search_limit_is_enforced_before_any_operation():
    with pytest.raises(ValueError):
        DevelopmentRank(project_id="test", results=[dict(id=str(i), revision=1) for i in range(11)])
