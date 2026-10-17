import json

import pytest

from opensubsurface.errors import DomainError
from opensubsurface.service import ref


def test_explicit_six_case_accounting_resume_only_failed_and_same_inputs(
    service, demo, tmp_path, monkeypatch
):
    pid = demo["project"]["id"]
    properties = [
        service.wait(
            service.invoke(
                "properties_assign",
                dict(
                    project_id=pid,
                    model=demo["model"],
                    zones={"1": dict(phi=phi, ntg=0.8, sw=0.25, permeability_md=100)},
                ),
            )
        )
        for phi in [0.15, 0.2, 0.25]
    ]
    base = dict(project_id=pid, properties=ref(properties[0]), demo_assumptions_accepted=True)
    schedules = [dict(base, producer_rate_sm3_day=rate) for rate in [50, 100]]
    original = service.invoke
    calls = []

    def mocked_solver(operation, args):
        if operation != "simulation_submit":
            return original(operation, args)
        calls.append(args.copy())
        job, _ = service.store.put_job(operation, args)
        if len(calls) in [2, 5]:
            service.store.update_job(
                job["id"], status="failed", error=dict(code="COMPUTE_FAILED", message="Injected failure")
            )
        else:
            series = tmp_path / ("mock-" + str(len(calls)) + ".json")
            series.write_text(json.dumps(dict(note="Explicit mocked solver fixture; no physical forecast")))
            obj = service.store.publish(
                pid, "simulation_result", dict(source="test-double"), {"series.json": series}
            )
            service.store.update_job(job["id"], status="succeeded", result=ref(obj))
        return dict(status="accepted", job_id=job["id"])

    monkeypatch.setattr(service, "invoke", mocked_solver)
    request = dict(
        project_id=pid,
        property_realizations=[ref(p) for p in properties],
        schedules=schedules,
        expected_case_count=6,
    )
    plan = original("ensemble_plan", request)
    assert plan["case_count"] == 6 and len({r["combination_id"] for r in plan["rows"]}) == 6
    submission = original("ensemble_run", request)
    with pytest.raises(DomainError, match="child"):
        service.wait(submission)
    first_job = service.store.job(submission["job_id"])
    partial = service.store.object(pid, first_job["result"])
    assert (
        partial["summary"]["total"] == 6
        and partial["summary"]["completed"] == 4
        and partial["summary"]["failed"] == 2
    )
    assert len(first_job["child_jobs"]) == 12  # Six real exporters + six mocked solver jobs.
    first_case_refs = [r["case"] for r in partial["summary"]["rows"]]
    second = service.wait(original("ensemble_run", dict(request, resume_ensemble=ref(partial))))
    assert len(calls) == 8  # Four completed outputs are reused, two failed cases rerun.
    assert second["summary"]["completed"] == 6 and second["summary"]["pending"] == 0
    assert sum(r["reused"] for r in second["summary"]["rows"]) == 4
    assert [r["case"] for r in second["summary"]["rows"]] == first_case_refs
    assert [r["input_hash"] for r in second["summary"]["rows"]] == [
        r["input_hash"] for r in partial["summary"]["rows"]
    ]


def test_interrupted_parent_saves_completed_rows_for_resume(service, tmp_path):
    pid = service.invoke("project_create", dict(name="Recovery", vertical_datum="TEST"))["id"]
    payload = dict(project_id=pid, property_realizations=[], schedules=[], expected_case_count=2)
    obj = service.store.publish(pid, "simulation_result", dict(provenance="mock result"))
    child, _ = service.store.put_job("simulation_submit", dict(project_id=pid))
    service.store.update_job(child["id"], status="succeeded", result=ref(obj))
    parent, _ = service.store.put_job("ensemble_run", payload)
    rows = [
        dict(combination_id="a", input_hash="a", status="running", job_id=child["id"]),
        dict(combination_id="b", input_hash="b", status="planned", job_id=None),
    ]
    service.store.update_job(parent["id"], status="running", ensemble_rows=rows)
    service.start()
    recovered = service.store.job(parent["id"])
    assert recovered["status"] == "interrupted"
    snapshot = service.store.object(pid, recovered["result"])
    assert snapshot["summary"]["total"] == 2 and snapshot["summary"]["completed"] == 1
    assert snapshot["summary"]["rows"][1]["status"] == "interrupted"
