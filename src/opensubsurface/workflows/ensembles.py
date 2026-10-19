"""Explicit Cartesian plans, persistent row accounting and content-checked resume."""

import time

from opensubsurface.errors import DomainError, require
from opensubsurface.execution.provenance import fingerprint
from opensubsurface.persistence.store import digest, now
from opensubsurface.schemas import SimulationCaseCreate

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def reference(obj):
    return dict(id=obj["id"], revision=obj["revision"])


def build_plan(service, payload):
    service.preflight("simulation_submit", payload)
    runtime = fingerprint()
    rows = []
    pid = payload["project_id"]
    for realization in payload["property_realizations"]:
        properties = service.store.object(pid, realization)
        require(
            properties["kind"] == "properties", "TYPE_MISMATCH", "An ensemble requires property realizations"
        )
        require(
            not properties["summary"].get("model_summary", {}).get("fault"),
            "UNSUPPORTED_GRID_BRIDGE",
            "Faulted realizations are not supported by the OPM Cartesian bridge",
        )
        for index, schedule in enumerate(payload["schedules"]):
            require(
                schedule["project_id"] == pid,
                "PERMISSION_DENIED",
                "The schedule template belongs to another project",
            )
            args = SimulationCaseCreate.model_validate(dict(schedule, properties=realization)).model_dump(
                mode="json"
            )
            require(
                args["demo_assumptions_accepted"],
                "INVALID_PVT",
                "Confirm the synthetic demo PVT/SCAL for every schedule",
            )
            service.preflight("simulation_case_create", args)
            key = digest(
                dict(
                    case=args,
                    property_hash=properties["content_hash"],
                    schedule_index=index,
                    execution=payload["execution"],
                    runtime=runtime,
                )
            )
            rows.append(
                dict(
                    combination_id=key[:20],
                    input_hash=key,
                    properties=realization,
                    schedule=index,
                    seed=properties["parameters"].get("seed", properties["summary"].get("seed")),
                    arguments=args,
                    status="planned",
                    result=None,
                    case=None,
                    job_id=None,
                    reused=False,
                )
            )
    require(
        len(rows) == payload["expected_case_count"],
        "INVALID_ENSEMBLE",
        "The number of cases changed during planning",
    )
    return dict(
        schema_version=1,
        case_count=len(rows),
        rows=rows,
        plan_hash=digest(rows),
        runtime=runtime,
        target="local-cpu",
        cost="unknown; no managed cloud launch",
    )


def cached(store, pid, ref, kind):
    if not ref:
        return None
    try:
        obj = store.object(pid, ref)
        return obj if obj["kind"] == kind else None
    except DomainError as error:
        if error.code not in ("INPUT_REVISION_CONFLICT", "INTEGRITY_ERROR", "NOT_FOUND"):
            raise
        return None


def report(rows, compute_status=None):
    completed = sum(row["status"] == "succeeded" for row in rows)
    failed = sum(row["status"] in ("failed", "cancelled", "interrupted") for row in rows)
    return dict(
        total=len(rows),
        completed=completed,
        failed=failed,
        pending=len(rows) - completed - failed,
        rows=rows,
        compute_status=compute_status or ("completed" if completed == len(rows) else "partial_failure"),
        cleanup_status="not_applicable",
    )


def execute(service, job):
    payload = job["payload"]
    pid = payload["project_id"]
    plan = job.get("resolved_plan") or build_plan(service, payload)
    rows = plan["rows"]
    children = []
    previous = {}
    if payload.get("resume_ensemble"):
        old = service.store.object(pid, payload["resume_ensemble"])
        require(
            old["kind"] == "ensemble",
            "TYPE_MISMATCH",
            "resume_ensemble requires an immutable ensemble artifact",
        )
        previous = {row["combination_id"]: row for row in old["summary"]["rows"]}

    def persist(stage):
        service.store.update_job(job["id"], stage=stage, ensemble_rows=rows, child_jobs=children)

    def fail(row, error, stage):
        row.update(status="failed", error=error.as_dict(), failure_stage=stage, completed_at=now())

    try:
        # Register every combination before any compute, including combinations whose exporter fails.
        persist("Ensemble plan saved")
        pending_exports = []
        for row in rows:
            service.check_cancel(job["id"])
            old = previous.get(row["combination_id"], {})
            if old.get("input_hash") == row["input_hash"]:
                result = (
                    cached(service.store, pid, old.get("result"), "simulation_result")
                    if old.get("status") == "succeeded"
                    else None
                )
                if result:
                    row.update(
                        status="succeeded",
                        result=reference(result),
                        case=old.get("case"),
                        job_id=old.get("job_id"),
                        reused=True,
                        completed_at=now(),
                    )
                    continue
                old_case = cached(service.store, pid, old.get("case"), "simulation_case")
                if old_case:
                    row["case"] = reference(old_case)
            if row["case"] is None:
                submission = service.invoke("simulation_case_create", row["arguments"])
                children.append(submission["job_id"])
                row.update(status="creating_case", case_job_id=submission["job_id"])
                pending_exports.append((row, submission))
            persist("Preparing cases")
        for row, submission in pending_exports:
            service.check_cancel(job["id"])
            try:
                case = service.wait(submission)
                row.update(case=reference(case), status="case_ready")
            except DomainError as error:
                fail(row, error, "case_create")
            persist("Cases prepared")
        for row in rows:
            service.check_cancel(job["id"])
            if row["status"] in ("failed", "succeeded"):
                continue
            try:
                submission = service.invoke(
                    "simulation_submit",
                    dict(
                        project_id=pid,
                        case=row["case"],
                        execution=payload["execution"],
                        idempotency_key=job["id"] + "-" + row["combination_id"],
                    ),
                )
                children.append(submission["job_id"])
                row.update(status="running", job_id=submission["job_id"])
            except DomainError as error:
                fail(row, error, "submit")
            persist("Independent runs submitted")
        for row in rows:
            service.check_cancel(job["id"])
            if row["status"] != "running":
                continue
            try:
                result = service.wait(dict(job_id=row["job_id"]))
                row.update(status="succeeded", result=reference(result), completed_at=now())
            except DomainError as error:
                child = service.store.job(row["job_id"])
                row.update(
                    status=child["status"] if child["status"] in TERMINAL else "failed",
                    error=error.as_dict(),
                    failure_stage="compute",
                    completed_at=now(),
                )
            persist("Ensemble results collected")
    except Exception as original:
        error = (
            original
            if isinstance(original, DomainError)
            else DomainError("ENSEMBLE_FAILED", "Orchestration error: " + type(original).__name__)
        )
        # Cancel only owned child jobs and await native resource release before marking the parent cancelled.
        for child_id in children:
            service.cancel(child_id)
        deadline = time.monotonic() + 30
        while (
            any(service.store.job(child)["status"] not in TERMINAL for child in children)
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
        alive = [child for child in children if service.store.job(child)["status"] not in TERMINAL]
        if alive:
            error = DomainError(
                "CANCEL_TIMEOUT", "Stop of all child jobs was not confirmed: " + ",".join(alive)
            )
        for row in rows:
            if row["status"] in TERMINAL:
                continue
            child = service.store.job(row["job_id"]) if row.get("job_id") else None
            result = (
                cached(service.store, pid, child.get("result"), "simulation_result")
                if child and child["status"] == "succeeded"
                else None
            )
            if result:
                row.update(status="succeeded", result=reference(result), completed_at=now())
            else:
                status = (
                    child["status"]
                    if child and child["status"] in ("failed", "cancelled", "interrupted")
                    else "interrupted"
                )
                row.update(status=status, error=error.as_dict(), completed_at=now())
        persist("Ensemble interrupted; partial results saved")
        obj = service.store.publish(
            pid,
            "ensemble",
            report(rows, "cancelled" if error.code == "CANCELLED" else "failed"),
            parameters=payload,
            sources=payload["property_realizations"],
        )
        service.store.update_job(
            job["id"],
            status="cancelled" if error.code == "CANCELLED" else "failed",
            stage="Ensemble interrupted",
            result=reference(obj),
            error=error.as_dict(),
            completed_at=now(),
        )
        return None
    obj = service.store.publish(
        pid, "ensemble", report(rows), parameters=payload, sources=payload["property_realizations"]
    )
    return obj
