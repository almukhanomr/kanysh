import json

import pytest

from opensubsurface.adapters.local_sources import LocalSources
from opensubsurface.errors import DomainError
from opensubsurface.service import ref


def specification(pid, **updates):
    spec = dict(
        project_id=pid,
        name="Analytical static fixture",
        method="horizontal_explicit",
        horizontal_assumption=True,
        grid=dict(shape=[3, 4, 2], extent=[0, 1000, 0, 1000, -1020, -1000]),
        zones={"1": dict(phi=0.2, ntg=0.8, sw=0.25, permeability_md=100)},
        zone_ids=[1],
        bo=1.2,
        contacts=[dict(name="full", z_m=-1020), dict(name="half", z_m=-1010), dict(name="dry", z_m=-1000)],
        assumptions=["Synthetic homogeneous rectangular reservoir; not a field forecast"],
    )
    spec.update(updates)
    return spec


def project(service):
    return service.invoke("project_create", dict(name="Calculation", vertical_datum="TEST"))["id"]


def test_missing_scientific_inputs_return_questions_without_compute(service):
    pid = project(service)
    result = service.invoke("calculation_plan", dict(project_id=pid))
    assert result["status"] == "NEEDS_INPUT" and not result["compute_started"]
    assert {q["field"] for q in result["questions"]} >= {"grid", "bo", "zones", "contacts", "assumptions"}
    assert service.store.list_jobs(pid) == [] and service.store.list_objects(pid) == []


def test_static_plan_runs_independent_validation_and_complete_report(service):
    pid = project(service)
    plan = service.invoke(
        "calculation_plan",
        specification(
            pid,
            uncertainty=dict(
                contact_name="full",
                distributions=dict(phi=dict(kind="uniform", low=0.15, high=0.25)),
                count=5,
                seed=17,
            ),
        ),
    )
    assert plan["summary"]["status"] == "READY" and service.store.list_jobs(pid) == []
    assert service.invoke("plan_validate", dict(project_id=pid, plan=ref(plan)))["status"] == "VALID"
    args = dict(project_id=pid, plan=ref(plan))
    submitted = service.invoke("calculation_run", args)
    assert service.invoke("calculation_run", args)["job_id"] == submitted["job_id"]
    finished = service.wait(submitted, timeout=90)
    assert finished["kind"] == "workflow_run"
    status = service.invoke("calculation_status", dict(project_id=pid, run_id=submitted["run_id"]))
    assert status["status"] == "succeeded" and status["report"]
    report = service.store.object(pid, status["report"])
    data = json.loads(service.store.path(report, "report.json").read_text())
    assert data["validation_status"] == "PASS" and data["geological_fitness"] == "REQUIRES_REVIEW"
    assert [c["STOIIP"] for c in data["contacts"]] == pytest.approx([2e6, 1e6, 0])
    assert data["uncertainty"]["count"] == 5 and data["uncertainty"]["seed"] == 17
    assert all(c["status"] == "PASS" for c in data["checks"] if c["required"])
    assert {"report.html", "report.md", "report.json", "volumes.png", "volumes.csv"} <= set(report["files"])
    assert service.store.path(report, "volumes.png").read_bytes().startswith(b"\x89PNG")


def test_source_bytes_are_pinned_and_plan_survives_source_revocation_and_bundle(service, tmp_path):
    pid = project(service)
    directory = tmp_path / "source"
    directory.mkdir()
    (directory / "collars.csv").write_text("well_id,x,y,reference_elevation\nW1,250,250,0\n")
    source = LocalSources(service.store).register("Fixture", directory)
    entry = service.invoke("source_scan", dict(source_id=source["id"]))["entries"][0]
    inspected = service.invoke(
        "source_inspect",
        dict(source_id=source["id"], path=entry["path"], file_revision=entry["file_revision"]),
    )
    assert "collars" in inspected["candidate_kinds"] and inspected["preview"] == []
    plan = service.invoke(
        "calculation_plan",
        specification(
            pid,
            inputs=[
                dict(
                    kind="collars",
                    source_id=source["id"],
                    path=entry["path"],
                    file_revision=entry["file_revision"],
                    units=dict(x="m", y="m", reference_elevation="m"),
                )
            ],
        ),
    )
    LocalSources(service.store).remove(source["id"])
    (directory / "collars.csv").write_text("Modified after snapshot")
    archive = tmp_path / "plan.zip"
    service.store.export_project(pid, archive)
    from opensubsurface.service import Service

    restored = Service(tmp_path / "restored")
    try:
        restored.store.import_project(archive)
        submitted = restored.invoke("calculation_run", dict(project_id=pid, plan=ref(plan)))
        restored.wait(submitted, timeout=90)
        status = restored.invoke("calculation_status", dict(project_id=pid, run_id=submitted["run_id"]))
        imported = restored.store.object(pid, status["artifacts"]["input_0"])
        assert imported["summary"]["rows"] == 1
        assert imported["parameters"]["input_file"]["source"]["plan"] == ref(plan)
    finally:
        restored.close()


def test_plan_runtime_and_project_boundaries_checked_before_jobs(service, monkeypatch):
    from opensubsurface.calculations import planning

    pid = project(service)
    plan = service.invoke("calculation_plan", specification(pid))
    other = project(service)
    with pytest.raises(DomainError):
        service.invoke("calculation_run", dict(project_id=other, plan=ref(plan)))
    monkeypatch.setattr(planning, "fingerprint", lambda: dict(incompatible=True))
    with pytest.raises(DomainError) as error:
        service.invoke("calculation_run", dict(project_id=pid, plan=ref(plan)))
    assert error.value.code == "STALE_PLAN" and service.store.list_jobs(pid) == []


def test_corrupt_blob_gets_failed_validation_instead_of_false_pass(service, demo):
    pid = demo["project"]["id"]
    volume = service.store.object(pid, demo["volumetrics"])
    service.store.path(volume, "result.json").write_text("corrupt bytes")
    validation = service.wait(service.invoke("result_validate", dict(project_id=pid, artifact=ref(volume))))
    assert validation["summary"]["status"] == "FAIL"


def test_wrong_numbers_with_valid_hashes_are_rejected_and_gate_parent_run(service, tmp_path, monkeypatch):
    pid = project(service)
    plan = service.invoke("calculation_plan", specification(pid))
    original = service.invoke

    def incorrect_volume(operation, args):
        if operation != "volumetrics_calculate":
            return original(operation, args)
        correct = service.wait(original(operation, args))
        wrong = dict(correct["summary"], values=dict(correct["summary"]["values"]))
        wrong["values"]["STOIIP"] += 100
        path = tmp_path / (correct["id"] + ".json")
        path.write_text(json.dumps(wrong))
        return service.store.publish(
            pid,
            "volumetrics",
            wrong,
            {"result.json": path},
            parameters=correct["parameters"],
            sources=correct["source_ids"],
        )

    monkeypatch.setattr(service, "invoke", incorrect_volume)
    submitted = original("calculation_run", dict(project_id=pid, plan=ref(plan)))
    with pytest.raises(DomainError) as error:
        service.wait(submitted, timeout=90)
    assert error.value.code == "VALIDATION_FAILED"
    status = original("calculation_status", dict(project_id=pid, run_id=submitted["run_id"]))
    report = service.store.object(pid, status["report"])
    evidence = json.loads(service.store.path(report, "report.json").read_text())
    assert evidence["validation_status"] == "FAIL"
    assert any(c["id"] == "volumes:STOIIP" and c["status"] == "FAIL" for c in evidence["checks"])


def test_unknown_validator_profile_is_incomplete(service):
    pid = project(service)
    unsupported = service.store.publish(
        pid, "simulation_result", dict(provenance="Unsupported test artifact; no forecast")
    )
    checked = service.wait(service.invoke("result_validate", dict(project_id=pid, artifact=ref(unsupported))))
    assert checked["summary"]["status"] == "INCOMPLETE"


def test_failed_partial_run_can_export_honest_incomplete_report(service, monkeypatch):
    pid = project(service)
    plan = service.invoke("calculation_plan", specification(pid))
    original = service.invoke

    def fail_model(operation, args):
        if operation == "model_build":
            raise DomainError("QC_FAILED", "Deliberate test failure")
        return original(operation, args)

    monkeypatch.setattr(service, "invoke", fail_model)
    submitted = original("calculation_run", dict(project_id=pid, plan=ref(plan)))
    with pytest.raises(DomainError):
        service.wait(submitted)
    report = service.wait(original("report_export", dict(project_id=pid, run_id=submitted["run_id"])))
    assert report["summary"]["validation_status"] == "INCOMPLETE" and report["summary"]["missing_nodes"]
    assert (
        json.loads(service.store.path(report, "report.json").read_text())["run_error"]["code"] == "QC_FAILED"
    )


def test_failed_calculation_resume_reuses_inputs_but_exports_report_for_new_run(service, monkeypatch):
    pid = project(service)
    plan = service.invoke("calculation_plan", specification(pid))
    original = service.invoke

    def fail_contact(operation, args):
        if operation == "volumetrics_calculate":
            raise DomainError("EXECUTOR_FAILED", "Deliberate recoverable worker failure")
        return original(operation, args)

    monkeypatch.setattr(service, "invoke", fail_contact)
    first = original("calculation_run", dict(project_id=pid, plan=ref(plan)))
    with pytest.raises(DomainError):
        service.wait(first)
    status = original("calculation_status", dict(project_id=pid, run_id=first["run_id"]))
    assert status["checkpoint"] and "properties" in status["artifacts"]
    monkeypatch.setattr(service, "invoke", original)
    resumed = original(
        "calculation_run", dict(project_id=pid, plan=ref(plan), resume_run=status["checkpoint"])
    )
    snapshot = service.wait(resumed)
    assert snapshot["summary"]["nodes"]["properties"]["reused"]
    status = original("calculation_status", dict(project_id=pid, run_id=resumed["run_id"]))
    report = service.store.object(pid, status["report"])
    assert status["status"] == "succeeded"
    assert report["summary"]["run_id"] == resumed["run_id"] != first["run_id"]
    assert report["summary"]["validation_status"] == "PASS"
