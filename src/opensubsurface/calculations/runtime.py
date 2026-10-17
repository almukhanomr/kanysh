import re

from opensubsurface.calculations import planning
from opensubsurface.calculations.schemas import (
    CalculationRun,
    PlanRequest,
    ResultPreview,
    RunRequest,
    SourceInspect,
)
from opensubsurface.errors import DomainError, require


def bound(service, obj):
    return dict(
        obj,
        paths={
            name: str(service.store.root / "blobs" / sha)
            for name, sha in obj["files"].items()
            if re.fullmatch(r"[a-f0-9]{64}", sha)
        },
    )


def validation_inputs(service, p):
    obj = service.store.object(p["project_id"], p["artifact"], verify=False)
    resolved = dict(artifact=bound(service, obj))
    parent = obj
    for port in ("properties", "model"):
        reference = parent["parameters"].get(port)
        if reference:
            parent = service.store.object(p["project_id"], reference, verify=False)
            resolved[port] = bound(service, parent)
    return resolved


def report_inputs(service, p):
    job, plan_obj, records = planning.run_context(service, p)
    require(job["status"] != "queued", "RUN_NOT_READY", "Run ещё не начал работу")
    resolved = dict(plan=bound(service, plan_obj))
    unavailable = {}
    for name, row in records.items():
        if name == "report":
            continue
        try:
            resolved[name] = bound(service, service.store.object(p["project_id"], row["result"]))
        except DomainError as error:
            unavailable[name] = error.as_dict()
    return resolved, dict(
        run_id=job["id"], parent_status=job["status"], error=job.get("error"), unavailable=unavailable
    )


def import_snapshot(service, p):
    plan_obj = service.store.object(p["project_id"], p["plan"])
    require(plan_obj["kind"] == "calculation_plan", "TYPE_MISMATCH", "Нужен calculation_plan")
    require(
        p["input_index"] < len(plan_obj["summary"]["inputs"]), "INVALID_ARGUMENTS", "Input index вне плана"
    )
    entry = plan_obj["summary"]["inputs"][p["input_index"]]
    with service.store.path(plan_obj, entry["file"]).open("rb") as stream:
        uploaded = service.store.upload(
            p["project_id"],
            entry["path"],
            stream,
            source=dict(
                plan=planning.ref(plan_obj),
                content_hash=entry["content_hash"],
                file_revision=entry["file_revision"],
            ),
        )
    require(
        uploaded["content_hash"] == entry["content_hash"], "INTEGRITY_ERROR", "Snapshot input hash mismatch"
    )
    return service.invoke(
        "dataset_import",
        dict(
            project_id=p["project_id"],
            upload_id=uploaded["id"],
            kind=entry["kind"],
            units=entry["units"],
            crs=plan_obj["summary"]["crs"],
            vertical_datum=plan_obj["summary"]["vertical_datum"],
            execution=p["execution"],
            idempotency_key=p["idempotency_key"],
        ),
    )


def invoke(service, operation, arguments):
    if operation == "calculation_plan":
        return planning.plan(service, arguments)
    schema = {
        "source_inspect": SourceInspect,
        "plan_validate": PlanRequest,
        "calculation_run": CalculationRun,
        "calculation_status": RunRequest,
        "result_preview": ResultPreview,
    }[operation]
    p = schema.model_validate(arguments).model_dump(mode="json")
    if operation == "source_inspect":
        return planning.inspect_source(service, p)
    if operation == "plan_validate":
        obj = planning.validate_plan(service, p)
        return dict(
            status="VALID", plan=planning.ref(obj), content_hash=obj["content_hash"], compute_started=False
        )
    if operation == "calculation_run":
        return planning.run(service, p)
    if operation == "calculation_status":
        return planning.status(service, p)
    obj = service.store.object(p["project_id"], p["report"])
    require(obj["kind"] in ("calculation_report", "analysis_report"), "TYPE_MISMATCH", "Expected report")
    filename = next(
        (name for name in ("volumes.png", "tornado.png", "s_curve.png") if name in obj["files"]),
        "report.json",
    )
    return dict(
        report=planning.ref(obj),
        mime_type="image/png" if filename.endswith(".png") else "application/json",
        filename=filename,
        validation_status=obj["summary"].get("validation_status", "NOT RUN"),
        resource_uri=f"opensubsurface://projects/{p['project_id']}/artifacts/{obj['id']}/{obj['revision']}/{filename}",
        download_path=f"/api/v1/projects/{p['project_id']}/artifacts/{obj['id']}/{obj['revision']}/files/{filename}",
        files=[
            dict(
                filename=name,
                download_path=f"/api/v1/projects/{p['project_id']}/artifacts/{obj['id']}/{obj['revision']}/files/{name}",
            )
            for name in obj["files"]
        ],
    )
