import csv
import io
import math
import os
from pathlib import Path

from opensubsurface.adapters.imports import REQUIRED
from opensubsurface.adapters.local_sources import LocalSources, revision
from opensubsurface.calculations.schemas import CalculationPlan
from opensubsurface.errors import DomainError, require
from opensubsurface.execution.provenance import fingerprint
from opensubsurface.persistence.store import digest


def ref(obj):
    return dict(id=obj["id"], revision=obj["revision"])


def inspect_source(service, p):
    if Path(p["path"]).suffix.lower() == ".json":
        from opensubsurface.adapters.large_grid import inspect_source as inspect_grid

        return inspect_grid(service, p)
    sources = LocalSources(service.store)
    with sources.opened(p["source_id"], p["path"]) as (fd, _):
        info = os.fstat(fd)
        require(revision(info) == p["file_revision"], "SOURCE_CHANGED", "Повторите source_scan")
        result = dict(
            path=p["path"],
            size_bytes=info.st_size,
            file_revision=p["file_revision"],
            scope="bounded header/sample; full QC occurs during import",
            candidate_kinds=[],
        )
        if Path(p["path"]).suffix.lower() != ".csv":
            return dict(result, status="UNSUPPORTED_INSPECTION", supported_format="CSV")
        raw = os.read(fd, 65536)
        require(
            revision(os.fstat(fd)) == p["file_revision"], "SOURCE_CHANGED", "Файл изменён во время чтения"
        )
        require(b"\n" in raw or len(raw) < 65536, "HEADER_TOO_LARGE", "CSV header превышает 64 KiB")
        try:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            columns = reader.fieldnames or []
            require(
                bool(columns) and len(columns) == len(set(columns)),
                "QC_FAILED",
                "Пустые/повторные CSV columns",
            )
            previews = []
            for _ in range(p.get("preview_rows", 0)):
                row = next(reader, None)
                if row is None:
                    break
                previews.append({key: str(value)[:200] for key, value in row.items() if key is not None})
        except (UnicodeError, csv.Error) as error:
            raise DomainError("INVALID_CSV", "Нужен CSV UTF-8 с доступным header/sample") from error
        return dict(
            result,
            status="INSPECTED",
            columns=columns,
            candidate_kinds=[kind for kind, required in REQUIRED.items() if set(required) <= set(columns)],
            preview=previews,
            preview_is_untrusted_data=True,
            bytes_read=len(raw),
        )


def requirements(spec):
    missing = []
    for field, question in {
        "grid": "Какие extent и shape использовать? Координаты — метры, Z вверх.",
        "method": "GemPy по surface points или явно горизонтальная модель?",
        "horizontal_assumption": "Разрешено ли явно предполагать горизонтальные слои?",
        "zones": "Какие phi/NTG/Sw/K задать каждой зоне и на каком основании?",
        "zone_ids": "Какие зоны входят в подсчёт?",
        "bo": "Какой Bo использовать?",
        "contacts": "Какие варианты OWC Z (м, вверх) сравнить?",
        "assumptions": "Какие предметные допущения приняты пользователем?",
    }.items():
        if spec.get("properties") and field in ("grid", "method", "horizontal_assumption", "zones"):
            continue
        if spec.get(field) is None or (field == "assumptions" and not spec[field]):
            missing.append(dict(field=field, question=question))
    roles = {entry["kind"] for entry in spec["inputs"]}
    if spec["method"] == "gempy":
        if "surfaces" not in roles:
            missing.append(dict(field="inputs.surfaces", question="Укажите CSV surface points."))
        if not spec["horizontal_assumption"] and "orientations" not in roles:
            missing.append(
                dict(
                    field="inputs.orientations",
                    question="Укажите orientations или разрешите horizontal_assumption.",
                )
            )
    elif spec["method"] == "horizontal_explicit":
        if spec["horizontal_assumption"] is not True:
            missing.append(
                dict(field="horizontal_assumption", question="Horizontal model требует явного true.")
            )
        if roles & {"surfaces", "orientations"}:
            missing.append(
                dict(
                    field="method",
                    question="Surface/orientation inputs требуют GemPy: horizontal_explicit их не использует.",
                )
            )
    for i, entry in enumerate(spec["inputs"]):
        for key in REQUIRED[entry["kind"]]:
            if key in ("x", "y", "z", "reference_elevation") and not entry["units"].get(key):
                missing.append(dict(field=f"inputs[{i}].units.{key}", question=f"Укажите единицу {key}."))
    if spec["uncertainty"] and spec["contacts"]:
        require(
            spec["uncertainty"]["contact_name"] in {c["name"] for c in spec["contacts"]},
            "INVALID_PLAN",
            "uncertainty.contact_name должен выбирать один contact",
        )
        for name, distribution in spec["uncertainty"]["distributions"].items():
            bounds = [distribution["low"]]
            if distribution["kind"] != "constant":
                bounds.append(distribution["high"])
            require(
                name not in ("phi", "ntg", "sw") or all(0 <= v <= 1 for v in bounds),
                "INVALID_PLAN",
                "Границы distribution должны быть в [0,1]",
            )
            require(
                name != "bo" or all(v > 0 for v in bounds),
                "INVALID_PLAN",
                "Bo distribution должен быть положительным",
            )
    if spec["zones"] and spec["zone_ids"]:
        require(
            set(map(str, spec["zone_ids"])) <= set(spec["zones"]), "INVALID_PLAN", "Нет свойств выбранных зон"
        )
    return missing


def plan(service, arguments):
    spec = CalculationPlan.model_validate(arguments).model_dump(mode="json")
    project = service.store.project(spec["project_id"])
    missing = requirements(spec)
    if spec["properties"]:
        from opensubsurface.adapters.large_grid import is_large

        require(
            not spec["inputs"]
            and all(spec[k] is None for k in ("grid", "method", "horizontal_assumption", "zones"))
            and not spec["horizons_z"]
            and not spec["stratigraphic_order"],
            "INVALID_PLAN",
            "Imported properties already define grid/structure; do not supply ignored model inputs",
        )
        props = service.store.object(spec["project_id"], spec["properties"])
        require(props["kind"] == "properties" and is_large(props), "TYPE_MISMATCH", "Use grid_import result")
        require(
            all(props["summary"][k] == project[k] for k in ("crs", "vertical_datum")),
            "INVALID_CRS",
            "Properties/project CRS or datum mismatch",
        )
        if missing:
            return dict(status="NEEDS_INPUT", questions=missing, spec=spec, inputs=[], compute_started=False)
        require(
            set(spec["zone_ids"]) <= set(props["summary"]["zone_ids"]),
            "INVALID_PLAN",
            "Selected zones are absent from imported properties",
        )
        if (
            spec["execution"]["device_policy"] != "cpu"
            and props["summary"].get("storage") != "cornerpoint-zarr-v1"
        ):
            from opensubsurface.service import no_gpu_error

            raise no_gpu_error(
                "calculation_plan", "plans on imported properties (corner-point/large grid) run on CPU blocks"
            )
        service.preflight("volumetrics_calculate", dict(execution=spec["execution"]))
        summary = dict(
            status="READY",
            profile=spec["profile"],
            name=spec["name"],
            inputs=[
                dict(
                    kind="properties",
                    artifact=spec["properties"],
                    content_hash=props["content_hash"],
                    source_format=props["summary"].get("source_format"),
                    order=props["summary"].get("order", "C"),
                    cartesian_basis=props["summary"].get("cartesian_basis"),
                )
            ],
            properties_content_hash=props["content_hash"],
            grid=props["summary"]["grid"],
            crs=project["crs"],
            vertical_datum=project["vertical_datum"],
            runtime=fingerprint(),
            storage=props["summary"]["storage"],
            estimated_working_bytes=props["summary"].get(
                "working_memory_bound_bytes", props["summary"].get("block_cells", 16384) * 2048
            ),
            scope="Chunked static volumes using declared cell geometry; geological fitness requires review",
        )
        return service.store.publish(
            spec["project_id"], "calculation_plan", summary, parameters=spec, sources=[ref(props)]
        )
    inspected = []
    for entry in spec["inputs"]:
        info = inspect_source(service, entry)
        require(
            entry["kind"] in info["candidate_kinds"],
            "INVALID_PLAN",
            "CSV columns не соответствуют выбранному kind",
        )
        inspected.append(info)
    if missing:
        return dict(
            status="NEEDS_INPUT", questions=missing, spec=spec, inputs=inspected, compute_started=False
        )
    # Validate all concrete numeric parameters before storing or submitting any numerical jobs.
    from opensubsurface.schemas import ModelBuild, ScenariosRun

    model = dict(
        project_id=spec["project_id"],
        grid=spec["grid"],
        method=spec["method"],
        horizontal_assumption=spec["horizontal_assumption"],
        horizons_z=spec["horizons_z"],
        stratigraphic_order=spec["stratigraphic_order"],
        execution=spec["execution"],
    )
    if spec["method"] == "horizontal_explicit":
        require(
            len(set(spec["horizons_z"])) == len(spec["horizons_z"])
            and all(spec["grid"]["extent"][4] < z < spec["grid"]["extent"][5] for z in spec["horizons_z"]),
            "INVALID_PLAN",
            "Неверные горизонтальные границы",
        )
        require(
            set(map(str, range(1, len(spec["horizons_z"]) + 2))) <= set(spec["zones"]),
            "INVALID_PLAN",
            "Нужны свойства всех зон горизонтальной модели",
        )
        model["execution"] = dict(spec["execution"], device_policy="cpu")
    model = ModelBuild.model_validate(model).model_dump(mode="json")
    service.preflight("model_build", model)
    service.preflight("volumetrics_calculate", dict(execution=spec["execution"], grid=spec["grid"]))
    if spec["uncertainty"]:
        u = spec["uncertainty"]
        ScenariosRun.model_validate(
            dict(
                project_id=spec["project_id"],
                properties=dict(id="pending", revision=1),
                distributions=u["distributions"],
                count=u["count"],
                seed=u["seed"],
            )
        )
    require(
        sum(i["size_bytes"] for i in inspected) <= 512 * 1024**2, "PLAN_TOO_LARGE", "Input snapshots >512 MiB"
    )
    files, inputs = {}, []
    for i, entry in enumerate(spec["inputs"]):
        uploaded = LocalSources(service.store).upload(
            dict(
                project_id=spec["project_id"],
                **{key: entry[key] for key in ("source_id", "path", "file_revision")},
            )
        )
        filename = f"input-{i}.csv"
        files[filename] = service.store.upload_path(spec["project_id"], uploaded["id"])
        inputs.append(
            dict(
                **entry,
                file=filename,
                content_hash=uploaded["content_hash"],
                size_bytes=uploaded["size_bytes"],
            )
        )
    cells = math.prod(spec["grid"]["shape"])
    summary = dict(
        status="READY",
        profile=spec["profile"],
        name=spec["name"],
        inputs=inputs,
        crs=project["crs"],
        vertical_datum=project["vertical_datum"],
        runtime=fingerprint(),
        estimated_working_bytes=cells * 8 * 80,
        volume_evaluations=len(spec["contacts"])
        + (spec["uncertainty"]["count"] if spec["uncertainty"] else 0),
        scope="Initial oil in place, not recoverable reserves; geological fitness requires review",
        helper_operations_device="CPU; model GemPy and volumes follow declared execution policy",
    )
    return service.store.publish(spec["project_id"], "calculation_plan", summary, files, parameters=spec)


def validate_plan(service, p):
    obj = service.store.object(p["project_id"], p["plan"])
    require(obj["kind"] == "calculation_plan", "TYPE_MISMATCH", "Требуется calculation_plan")
    require(obj["summary"]["status"] == "READY", "INVALID_PLAN", "План не готов")
    require(
        obj["summary"]["runtime"] == fingerprint(),
        "STALE_PLAN",
        "Код/библиотеки/solver изменились: создайте новый план",
    )
    project = service.store.project(p["project_id"])
    require(
        all(project[k] == obj["summary"][k] for k in ("crs", "vertical_datum")),
        "INVALID_CRS",
        "CRS/datum проекта изменился",
    )
    spec = obj["parameters"]
    require(not requirements(spec), "INVALID_PLAN", "В плане отсутствуют допущения")
    if spec.get("properties"):
        props = service.store.object(p["project_id"], spec["properties"])
        require(
            props["content_hash"] == obj["summary"]["properties_content_hash"],
            "INTEGRITY_ERROR",
            "Properties changed",
        )
        service.preflight("volumetrics_calculate", dict(execution=spec["execution"]))
    else:
        service.preflight("volumetrics_calculate", dict(execution=spec["execution"], grid=spec["grid"]))
    return obj


def compile_nodes(plan):
    spec, pid, nodes = plan["parameters"], plan["project_id"], []

    def node(name, operation, **arguments):
        nodes.append(
            dict(id=name, operation=operation, depends_on=[], arguments=dict(project_id=pid, **arguments))
        )

    def n(name):
        return {"$node": name}

    if spec.get("properties"):
        node("properties", "properties_reference", properties=spec["properties"])
    else:
        roles = {}
        for i, entry in enumerate(plan["summary"]["inputs"]):
            name = f"input_{i}"
            node(name, "dataset_import_snapshot", plan=ref(plan), input_index=i)
            roles[entry["kind"]] = n(name)
        model_args = {
            k: spec[k]
            for k in ("grid", "method", "horizontal_assumption", "horizons_z", "stratigraphic_order")
        }
        model_args.update({k: v for k, v in roles.items() if k in ("surfaces", "orientations")})
        node(
            "model",
            "model_build",
            **model_args,
            execution=(
                spec["execution"]
                if spec["method"] == "gempy"
                else dict(spec["execution"], device_policy="cpu")
            ),
        )
        node("properties", "properties_assign", model=n("model"), zones=spec["zones"])
    for i, contact in enumerate(spec["contacts"]):
        node(
            f"contact_{i}",
            "volumetrics_calculate",
            properties=n("properties"),
            zone_ids=spec["zone_ids"],
            contact_z_m=contact["z_m"],
            bo=spec["bo"],
            execution=spec["execution"],
        )
    if spec["uncertainty"]:
        u = spec["uncertainty"]
        contact = next(c for c in spec["contacts"] if c["name"] == u["contact_name"])
        node(
            "uncertainty",
            "scenarios_run",
            properties=n("properties"),
            zone_ids=spec["zone_ids"],
            distributions=u["distributions"],
            count=u["count"],
            seed=u["seed"],
            bo=spec["bo"],
            contact_z_m=contact["z_m"],
            execution=spec["execution"],
        )
    artifacts = [entry["id"] for entry in nodes]
    for name in artifacts:
        node(
            "check_" + name,
            "result_validate",
            artifact=n(name),
            execution=dict(spec["execution"], device_policy="cpu"),
        )
    nodes.append(
        dict(
            id="report",
            operation="report_export",
            depends_on=["check_" + name for name in artifacts],
            arguments=dict(project_id=pid, run_id={"$run_id": True}),
        )
    )
    return nodes


def run(service, p):
    plan_obj = validate_plan(service, p)
    workflow_id = "calculation-workflow-" + plan_obj["content_hash"][:24]
    with service.lock:
        try:
            workflow = service.store.object(p["project_id"], dict(id=workflow_id, revision=1))
        except DomainError as error:
            if error.code != "INPUT_REVISION_CONFLICT":
                raise
            nodes = compile_nodes(plan_obj)
            workflow = service.store.publish(
                p["project_id"],
                "workflow",
                dict(profile="static_volumetrics_v1"),
                parameters=dict(
                    name=plan_obj["summary"]["name"],
                    nodes=nodes,
                    calculation_plan=ref(plan_obj),
                    result_gate_node="report",
                ),
                sources=[ref(plan_obj)],
                object_id=workflow_id,
            )
    if p.get("resume_run"):
        old = service.store.object(p["project_id"], p["resume_run"])
        require(
            old["kind"] == "workflow_run" and old["parameters"]["workflow"] == ref(workflow),
            "INVALID_RESUME",
            "Resume должен относиться к этому плану",
        )
    key = p.get("idempotency_key") or "calculation:" + digest(
        dict(plan=p["plan"], resume=p.get("resume_run"))
    )
    result = service.invoke(
        "workflow_run",
        dict(
            project_id=p["project_id"],
            workflow=ref(workflow),
            idempotency_key=key,
            resume_run=p.get("resume_run"),
        ),
    )
    return dict(result, run_id=result["job_id"], plan=ref(plan_obj))


def run_context(service, p):
    job = service.store.job(p["run_id"])
    require(job["project_id"] == p["project_id"], "PERMISSION_DENIED", "Run недоступен этому проекту")
    require(job["operation"] == "workflow_run", "TYPE_MISMATCH", "Нужен calculation run")
    workflow = service.store.object(p["project_id"], job["payload"]["workflow"])
    require("calculation_plan" in workflow["parameters"], "TYPE_MISMATCH", "Это не calculation run")
    plan_obj = service.store.object(p["project_id"], workflow["parameters"]["calculation_plan"])
    records = dict(job.get("node_results", {}))
    if job.get("result"):
        snapshot = service.store.object(p["project_id"], job["result"])
        records.update(snapshot["summary"].get("nodes", {}))
    return job, plan_obj, records


def workflow_progress(service, job):
    """Fraction of workflow nodes finished, counting running children by their own progress."""
    import time
    from datetime import datetime

    try:
        workflow = service.store.object(job["project_id"], job["payload"]["workflow"])
        total = len(workflow["parameters"]["nodes"])
    except (DomainError, KeyError):
        return dict(progress=None, eta_s=None, message=None, nodes={})
    states = job.get("node_states") or {}
    done, running, nodes = 0.0, [], {}
    for name, state in states.items():
        row = dict(state)
        if state["status"] in ("succeeded", "reused"):
            done += 1
        elif state["status"] == "running" and state.get("job_id"):
            child = service.store.job(state["job_id"])
            child_progress = service.progress(child) if child["status"] != "succeeded" else {"progress": 1.0}
            fraction = child_progress.get("progress")
            row.update(child_status=child["status"], progress=fraction, eta_s=child_progress.get("eta_s"))
            done += min(max(fraction or 0.0, 0.0), 0.99)
            running.append(name)
        nodes[name] = row
    if job["status"] == "succeeded":
        return dict(progress=1.0, eta_s=0.0, message="completed", nodes=nodes)
    fraction = done / total if total else None
    eta = None
    if fraction and job.get("started_at") and job["status"] in ("running", "cancel_requested"):
        started = datetime.fromisoformat(job["started_at"]).timestamp()
        elapsed = max(time.time() - started, 0.0)
        eta = round(elapsed * (1 - fraction) / fraction, 1)
    message = (
        f"{int(sum(1 for s in states.values() if s['status'] in ('succeeded', 'reused')))}/{total} nodes done"
        + ("; running: " + ", ".join(sorted(running)) if running else "")
    )
    return dict(
        progress=None if fraction is None else round(fraction, 4), eta_s=eta, message=message, nodes=nodes
    )


def status(service, p):
    job, plan_obj, records = run_context(service, p)
    progress = workflow_progress(service, job)
    return dict(
        run_id=job["id"],
        status=job["status"],
        stage=job.get("stage"),
        progress=progress["progress"],
        eta_s=progress["eta_s"],
        progress_message=progress["message"],
        nodes=progress["nodes"],
        plan=ref(plan_obj),
        checkpoint=job.get("result"),
        error=job.get("error"),
        artifacts={name: row["result"] for name, row in records.items()},
        report=records.get("report", {}).get("result"),
    )
