import importlib.metadata
import json
import os
import threading
import time
from pathlib import Path

import numpy as np
import portalocker

from opensubsurface.adapters.imports import check_coordinates
from opensubsurface.errors import DomainError, require
from opensubsurface.execution.provenance import fingerprint
from opensubsurface.execution.runner import run_isolated, stop_orphan
from opensubsurface.persistence.store import Store, canonical, digest, now, uid
from opensubsurface.schemas import (
    OPERATION_SCHEMAS,
    Inspect,
    JobRequest,
    ProjectCreate,
    ProjectRequest,
    SourceScan,
    SourceUpload,
)
from opensubsurface.workflows import engine

GPU_OPERATIONS = {"model_build", "volumetrics_calculate", "scenarios_run", "seismic_attribute"}
HEAVY = set(OPERATION_SCHEMAS) - {
    "workflow_save",
    "workflow_run",
    "ensemble_plan",
    "ensemble_run",
    "scenarios_compare",
    "simulation_compare",
    "ensemble_compare",
    "scene_show",
    "development_rank",
    "dataset_import_snapshot",
    "properties_reference",
}
REF_FIELDS = {
    "other_properties",
    "polygon",
    "trajectory",
    "model",
    "properties",
    "surfaces",
    "orientations",
    "fault",
    "volume",
    "interpretation",
    "case",
    "result",
    "plan",
}
EXPECTED_KINDS = {
    "other_properties": {"properties"},
    "polygon": {"dataset"},
    "trajectory": {"dataset"},
    "plan": {"calculation_plan"},
    "model": {"model"},
    "properties": {"properties"},
    "surfaces": {"dataset"},
    "orientations": {"dataset"},
    "volume": {"seismic"},
    "interpretation": {"interpretation"},
    "case": {"simulation_case"},
    "result": {"simulation_result"},
    "fault": {"fault"},
}
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def ref(obj):
    return {"id": obj["id"], "revision": obj["revision"]}


class Service:
    def __init__(self, root=None):
        self.store = Store(root or os.environ.get("OPENSUBSURFACE_HOME", ".data"))
        self.client = self.cluster = self.file_lock = None
        self.owns_controller = False
        self.lock = threading.RLock()
        self.threads = []
        self.closed = False

    def start(self):
        with self.lock:
            if self.client:
                return
            self.file_lock = (self.store.root / "control-plane.lock").open("a+")
            try:
                portalocker.lock(self.file_lock, portalocker.LOCK_EX | portalocker.LOCK_NB)
            except portalocker.exceptions.LockException:
                self.file_lock.close()
                self.file_lock = None
                raise DomainError(
                    "CONTROL_PLANE_ACTIVE", "Уже запущен control plane; используйте его REST API"
                )
            self.owns_controller = True
            self.recover_jobs()
            from distributed import Client, LocalCluster

            self.cluster = LocalCluster(
                n_workers=1,
                threads_per_worker=2,
                processes=False,
                protocol="inproc",
                dashboard_address="127.0.0.1:0",
                worker_dashboard_address="127.0.0.1:0",
                resources={"GPU": 1},
                silence_logs=40,
            )
            self.client = Client(self.cluster)

    def recover_jobs(self):
        active = [job for job in self.store.list_jobs(limit=None) if job["status"] not in TERMINAL]
        parents = []
        for job in active:
            if job["operation"] in ("workflow_run", "ensemble_run"):
                parents.append(job)
                continue
            directory = self.store.root / "attempts" / job["attempt_id"]
            if directory.exists():
                (directory / "cancel").touch()
                stop_orphan(directory)
            self.store.update_job(
                job["id"],
                status="interrupted",
                stage="Прервано после рестарта",
                error=dict(
                    code="CONTROL_PLANE_RESTART", message="Не подтверждено завершение прежнего executor"
                ),
            )
        for job in parents:
            payload = job["payload"]
            result_ref = None
            if job["operation"] == "ensemble_run":
                from opensubsurface.workflows.ensembles import cached, report

                rows = job.get("ensemble_rows") or job.get("resolved_plan", {}).get("rows", [])
                for row in rows:
                    if row["status"] == "succeeded" and cached(
                        self.store, job["project_id"], row.get("result"), "simulation_result"
                    ):
                        continue
                    child = self.store.job(row["job_id"]) if row.get("job_id") else None
                    output = (
                        cached(self.store, job["project_id"], child.get("result"), "simulation_result")
                        if child and child["status"] == "succeeded"
                        else None
                    )
                    if output:
                        row.update(status="succeeded", result=ref(output))
                    else:
                        row.update(status="interrupted", error=dict(code="CONTROL_PLANE_RESTART"))
                    if row.get("case_job_id") and row.get("case") is None:
                        case_job = self.store.job(row["case_job_id"])
                        case = (
                            cached(self.store, job["project_id"], case_job.get("result"), "simulation_case")
                            if case_job["status"] == "succeeded"
                            else None
                        )
                        if case:
                            row["case"] = ref(case)
                obj = self.store.publish(
                    job["project_id"],
                    "ensemble",
                    report(rows, "interrupted"),
                    parameters=payload,
                    sources=payload.get("property_realizations", []),
                )
                result_ref = ref(obj)
            else:
                obj = self.store.publish(
                    job["project_id"],
                    "workflow_run",
                    dict(
                        nodes=job.get("node_results", {}),
                        compute_status="interrupted",
                        cleanup_status="not_applicable",
                    ),
                    parameters=payload,
                    sources=[payload["workflow"]],
                )
                result_ref = ref(obj)
            self.store.update_job(
                job["id"],
                status="interrupted",
                stage="Прервано; snapshot для resume сохранён",
                result=result_ref,
                error=dict(code="CONTROL_PLANE_RESTART", message="Повторите с resume ref"),
            )

    def close(self):
        self.closed = True
        if self.owns_controller:
            for job in self.store.list_jobs(limit=None):
                if job["status"] not in TERMINAL:
                    self.cancel(job["id"])
        for thread in self.threads:
            thread.join(timeout=10)
        if self.client:
            self.client.close()
            self.cluster.close()
            self.client = None
        if self.file_lock:
            portalocker.unlock(self.file_lock)
            self.file_lock.close()
            self.file_lock = None
        self.owns_controller = False
        self.store.engine.dispose()

    def capabilities(self):
        import platform
        import shutil
        import sys

        import psutil
        import torch

        cuda = torch.cuda.is_available()
        memory = psutil.virtual_memory()
        devices = (
            [
                dict(
                    index=index,
                    name=torch.cuda.get_device_name(index),
                    vram_total_bytes=torch.cuda.get_device_properties(index).total_memory,
                )
                for index in range(torch.cuda.device_count())
            ]
            if cuda
            else []
        )
        return dict(
            profile="local-cpu" if not cuda else "local-cuda-unvalidated",
            cpu=True,
            cuda_available=cuda,
            cuda_device=torch.cuda.get_device_name(0) if cuda else None,
            cuda_devices=devices,
            host=dict(system=platform.system(), machine=platform.machine(), logical_cpus=psutil.cpu_count()),
            memory=dict(total_bytes=memory.total, available_bytes=memory.available),
            opm_available=sys.platform == "linux"
            and shutil.which(os.environ.get("OPENSUBSURFACE_FLOW_EXECUTABLE", "flow")) is not None,
            simulation_requirement="OPM Flow requires Linux/WSL; native Windows simulation is unavailable",
            remote_execution="not configured",
            large_models=dict(
                storage="cartesian-zarr-flat-v1",
                import_format="Cartesian NPY / GRDECL properties manifest",
                max_cells=2_000_000_000,
                max_block_cells=1048576,
                operations=["grid_import", "volumetrics_calculate", "scenarios_run", "result_validate"],
                device="CPU",
                gempy_out_of_core=False,
            ),
            cornerpoint=dict(
                import_formats=["DATA", "GRDECL", "EGRID", "ROFF"],
                limit_scope="max_cells applies only to legacy XTGeo geometry; static DATA uses static_deck below",
                max_cells=2000000,
                import_geometry="full RAM with preflight",
                calculations="chunked CPU tetra6",
                native_petrel_project=False,
            ),
            static_deck=dict(
                operation="eclipse_import",
                storage="cornerpoint-zarr-v1",
                geometry="Bounded COORD/ZCORN blocks; ASCII DATA/GRDECL only",
                parser_limit_cells=500_000_000,
                max_block_cells=16384,
                demonstrated_cells=20_000_000,
                demonstrated_peak_rss_bytes=1458208768,
                demonstrated_scope="Synthetic regular corner-point grid, complete geometry/property comparison; not large field EGRID acceptance",
                norne_full_data="Static import PASS; equilibrium SWAT and OPM NOT RUN",
                unsupported_keywords="Explicit file/line report; never silently applied",
                device="CPU",
            ),
            copilot=dict(
                operations=[
                    "folder_assess",
                    "eclipse_import",
                    "geodata_import",
                    "model_qc",
                    "volumes_reconcile",
                    "wells_vs_model",
                    "model_diff",
                    "regional_volumes",
                    "sensitivity_tornado",
                    "uncertainty_monte_carlo",
                    "results_export",
                ],
                reports=["HTML", "JSON", "CSV", "PNG", "XLSX", "PDF"],
                proposals="File/line candidates require explicit user confirmation before plans/calculations",
                geological_fitness="REQUIRES_REVIEW",
                windows_wsl_gpu_acceptance="NOT RUN",
                claude_desktop_extension_install="NOT RUN",
            ),
            scene=dict(
                backend="PyVista/trame offline HTML",
                extra="viewer",
                max_cells=200000,
                max_points=500000,
                persisted=True,
                twt_overlay="explicit velocity/origin required",
            ),
            large_seismic=dict(
                operation="seismic_source_import",
                dtype="float32",
                max_input_bytes=1024**4,
                profile="sorted regular zero-offset poststack; two bounded passes",
                openvds=False,
            ),
            modules={
                name: importlib.metadata.version(name)
                for name in ("gempy", "gstools", "segyio", "dask", "mcp")
            },
        )

    def preflight(self, operation, payload):
        execution = payload["execution"]
        require(
            execution["precision"] == "float64",
            "UNSUPPORTED_PRECISION",
            "Профиль float32 ещё не прошёл численную проверку; используйте float64",
        )
        require(
            execution["placement"] != "remote" and execution["target_id"] in (None, "local-cpu"),
            "TARGET_UNREACHABLE",
            "Удалённый target не настроен; передача данных не разрешена",
        )
        device = "cpu"
        warnings = []
        if execution["device_policy"] != "cpu":
            caps = self.capabilities()
            compatible = operation in GPU_OPERATIONS and (
                operation != "model_build" or payload["method"] == "gempy"
            )
            if compatible and caps["cuda_available"]:
                device = "cuda"
            else:
                require(
                    execution["device_policy"] != "require_gpu" and execution["allow_cpu_fallback"],
                    "NO_COMPATIBLE_GPU",
                    "Нет совместимого CUDA path для операции",
                )
                warnings.append("CPU fallback: CUDA недоступна или операция поддерживает только CPU")
        # Conservative estimate for base arrays + scientific working buffers; never downsample automatically.
        import psutil

        shape = (payload.get("grid") or {}).get("shape") or payload.get("shape")
        if shape:
            estimated = int(np.prod(shape)) * 8 * 80
            require(
                estimated < psutil.virtual_memory().available * 0.65,
                "INSUFFICIENT_MEMORY",
                "Оценка рабочих буферов превышает доступную RAM",
            )
        return device, warnings

    def resolve_inputs(self, operation, payload):
        if operation == "result_validate":
            from opensubsurface.calculations.runtime import validation_inputs

            return validation_inputs(self, payload)
        if operation == "report_export":
            from opensubsurface.calculations.runtime import report_inputs

            return report_inputs(self, payload)[0]
        resolved = {}
        for key in REF_FIELDS:
            if payload.get(key) is None:
                continue
            obj = self.store.object(payload["project_id"], payload[key])
            require(obj["kind"] in EXPECTED_KINDS[key], "TYPE_MISMATCH", f"Неверный тип входа {key}")
            if key in ("surfaces", "orientations"):
                require(obj["summary"].get("kind") == key, "TYPE_MISMATCH", f"Нужен dataset kind={key}")
            resolved[key] = dict(obj, paths={k: str(self.store.path(obj, k)) for k in obj["files"]})
        if operation == "results_export":
            for index, reference in enumerate(payload["slices"]):
                obj = self.store.object(payload["project_id"], reference)
                require(obj["kind"] == "seismic_slice", "TYPE_MISMATCH", "Expected seismic slice")
                resolved[f"slice_{index}"] = dict(
                    obj, paths={k: str(self.store.path(obj, k)) for k in obj["files"]}
                )
            for index, reference in enumerate(payload["reports"]):
                obj = self.store.object(payload["project_id"], reference)
                require(
                    obj["kind"] in ("analysis_report", "calculation_report")
                    and "report.json" in obj["files"],
                    "TYPE_MISMATCH",
                    "Expected immutable JSON report",
                )
                resolved[f"report_{index}"] = dict(
                    obj, paths={k: str(self.store.path(obj, k)) for k in obj["files"]}
                )
        if operation == "wells_vs_model":
            for index, log in enumerate(payload["logs"]):
                obj = self.store.object(payload["project_id"], log["ref"])
                require(
                    obj["kind"] == "dataset" and obj["summary"].get("kind") == "las",
                    "TYPE_MISMATCH",
                    "Original LAS dataset required",
                )
                resolved[f"las_{index}"] = dict(
                    obj, paths={k: str(self.store.path(obj, k)) for k in obj["files"]}
                )
        return resolved

    def invoke(self, operation, arguments):
        if operation == "start":
            from opensubsurface.onboarding import welcome
            from opensubsurface.schemas import Strict

            Strict.model_validate(arguments)
            return welcome(self)
        if operation == "folder_assess":
            from opensubsurface.adapters.folder_assess import assess
            from opensubsurface.schemas import FolderAssess

            return assess(self.store, FolderAssess.model_validate(arguments).model_dump())
        if operation in (
            "source_inspect",
            "calculation_plan",
            "plan_validate",
            "calculation_run",
            "calculation_status",
            "result_preview",
        ):
            from opensubsurface.calculations.runtime import invoke

            return invoke(self, operation, arguments)
        if operation == "project_create":
            data = ProjectCreate.model_validate(arguments).model_dump()
            check_coordinates(data["crs"], data["vertical_datum"])
            return self.store.create_project(data)
        if operation == "project_list":
            return self.store.list_projects()
        if operation in ("source_list", "source_scan", "source_upload"):
            from opensubsurface.adapters.local_sources import LocalSources

            sources = LocalSources(self.store)
            if operation == "source_list":
                return sources.list()
            if operation == "source_scan":
                return sources.scan(SourceScan.model_validate(arguments).model_dump())
            return sources.upload(SourceUpload.model_validate(arguments).model_dump())
        if operation == "project_inspect":
            p = ProjectRequest.model_validate(arguments)
            return dict(
                project=self.store.project(p.project_id),
                objects=self.store.list_objects(p.project_id),
                jobs=self.store.list_jobs(p.project_id),
            )
        if operation in (
            "artifact_inspect",
            "seismic_inspect",
            "simulation_results",
        ):
            p = Inspect.model_validate(arguments)
            return self.store.object(p.project_id, p.ref)
        if operation in ("dataset_validate", "simulation_validate"):
            p = Inspect.model_validate(arguments)
            return self.invoke("result_validate", dict(project_id=p.project_id, artifact=p.ref.model_dump()))
        if operation == "compute_targets_list":
            return [dict(id="local-cpu", location="local", health="ready", capabilities=self.capabilities())]
        if operation == "job_logs":
            job_id = JobRequest.model_validate(arguments).job_id
            job = self.store.job(job_id)
            directory = self.store.root / "attempts" / job["attempt_id"]
            logs = {}
            for name, path in [
                ("worker", directory / "worker.log"),
                ("solver", directory / "output" / "solver.log"),
            ]:
                if path.is_file():
                    with path.open("rb") as stream:
                        stream.seek(max(0, path.stat().st_size - 65536))
                        logs[name] = stream.read().decode("utf-8", errors="replace")
            return dict(job_id=job_id, attempt_id=job["attempt_id"], tail_bytes_per_log=65536, logs=logs)
        if operation in ("job_status", "job_cancel"):
            job_id = JobRequest.model_validate(arguments).job_id
            return self.store.job(job_id) if operation == "job_status" else self.cancel(job_id)
        if operation in ("workflow_status", "workflow_cancel"):
            job_id = JobRequest.model_validate(arguments).job_id
            return self.store.job(job_id) if operation == "workflow_status" else self.cancel(job_id)
        if operation == "scene_inspect":
            p = ProjectRequest.model_validate(arguments)
            self.store.project(p.project_id)
            return self.store.get_state("scene:" + p.project_id, {})
        if operation == "workflow_validate":
            p = Inspect.model_validate(arguments)
            obj = self.store.object(p.project_id, p.ref)
            return dict(order=engine.validate(obj["parameters"]["nodes"]), status="valid")
        require(operation in OPERATION_SCHEMAS, "UNSUPPORTED_OPERATION", "Неизвестная операция")
        p = OPERATION_SCHEMAS[operation].model_validate(arguments).model_dump(mode="json")
        self.store.project(p["project_id"])
        if operation == "properties_reference":
            obj = self.store.object(p["project_id"], p["properties"])
            require(obj["kind"] == "properties", "TYPE_MISMATCH", "Нужны свойства")
            return obj
        if operation == "dataset_import_snapshot":
            from opensubsurface.calculations.runtime import import_snapshot

            return import_snapshot(self, p)
        if operation == "workflow_save":
            order = engine.validate(p["nodes"])
            return self.store.publish(
                p["project_id"], "workflow", dict(name=p["name"], order=order), parameters=p
            )
        if operation == "scene_show":
            obj = self.store.object(p["project_id"], p["ref"])
            scene = self.store.get_state("scene:" + p["project_id"], {})
            scene[obj["id"]] = p
            self.store.set_state("scene:" + p["project_id"], scene)
            return scene
        if operation.endswith("_compare") or operation == "development_rank":
            return self.compare(operation, p)
        if operation == "ensemble_plan":
            from opensubsurface.workflows.ensembles import build_plan

            return build_plan(self, p)
        if operation in ("workflow_run", "ensemble_run"):
            return self.submit_orchestrator(operation, p)
        self.start()
        device, warnings = self.preflight(operation, p)
        resolved = self.resolve_inputs(operation, p)
        scene_context = None
        if operation == "scene_export":
            scene_context = self.store.get_state("scene:" + p["project_id"], {})
            require(0 < len(scene_context) <= 32, "INVALID_SCENE", "Scene requires 1–32 objects")
            for key, item in scene_context.items():
                obj = self.store.object(p["project_id"], item["ref"])
                resolved[key] = dict(
                    obj, paths={name: str(self.store.path(obj, name)) for name in obj["files"]}
                )
        from opensubsurface.adapters.large_grid import is_large

        for obj in resolved.values():
            if is_large(obj):
                require(
                    operation
                    in (
                        "volumetrics_calculate",
                        "scenarios_run",
                        "result_validate",
                        "report_export",
                        "scene_export",
                        "model_qc",
                        "model_diff",
                        "regional_volumes",
                        "volumes_reconcile",
                        "wells_vs_model",
                        "sensitivity_tornado",
                        "uncertainty_monte_carlo",
                    ),
                    "UNSUPPORTED_LARGE_OPERATION",
                    "Для этой операции нет блочного backend",
                )
                if device != "cpu":
                    require(
                        p["execution"]["device_policy"] != "require_gpu"
                        and p["execution"]["allow_cpu_fallback"],
                        "NO_COMPATIBLE_GPU",
                        "Large-grid backend currently CPU only",
                    )
                    device = "cpu"
                    warnings.append("CPU fallback: large-grid backend")
        source_context = None
        if operation == "volumes_reconcile":
            from opensubsurface.adapters.source_files import prepare_file

            source_context = prepare_file(self, p)
        if operation == "grid_import":
            from opensubsurface.adapters.large_grid import prepare

            source_context = prepare(self, p)
            project = self.store.project(p["project_id"])
            require(
                all(source_context["manifest"][k] == project[k] for k in ("crs", "vertical_datum")),
                "INVALID_CRS",
                "CRS/datum импорта должны совпадать с проектом",
            )
        if operation in ("seismic_source_import", "eclipse_import", "geodata_import"):
            from opensubsurface.adapters.source_files import prepare_file

            source_context = prepare_file(self, p)
            project = self.store.project(p["project_id"])
            require(
                all(p[k] == project[k] for k in ("crs", "vertical_datum")),
                "INVALID_CRS",
                "CRS/datum must match project",
            )
        block_cells = p.get("block_cells") or max(
            (o["summary"].get("block_cells", 0) for o in resolved.values()), default=0
        )
        if block_cells:
            import psutil

            require(
                block_cells * 192 + 128 * 1024**2 < psutil.virtual_memory().available * 0.65,
                "INSUFFICIENT_MEMORY",
                "Недостаточно RAM для блочного backend",
            )
        report_context = None
        if operation == "report_export":
            from opensubsurface.calculations.runtime import report_inputs

            resolved, report_context = report_inputs(self, p)
        if p.get("previous"):
            previous = self.store.object(p["project_id"], p["previous"])
            require(previous["kind"] == "interpretation", "TYPE_MISMATCH", "previous требует interpretation")
        upload_path = None
        upload_record = None
        context = None
        if operation in ("dataset_import", "seismic_import"):
            project = self.store.project(p["project_id"])
            require(
                p["crs"] == project["crs"] and p["vertical_datum"] == project["vertical_datum"],
                "INVALID_CRS",
                "CRS/datum импорта должны совпадать с проектом; неявное преобразование запрещено",
            )
            context = []
            for obj in self.store.list_objects(p["project_id"]):
                if obj["kind"] == "dataset" and "data.parquet" in obj["files"]:
                    context.append(
                        dict(
                            summary=obj["summary"],
                            paths={"data.parquet": str(self.store.path(obj, "data.parquet"))},
                        )
                    )
        if operation in ("dataset_import", "seismic_import"):
            upload_path = str(self.store.upload_path(p["project_id"], p["upload_id"]))
            upload_record = self.store.upload_record(p["project_id"], p["upload_id"])
        job, created = self.store.put_job(operation, p)
        if created:
            request = dict(
                operation=operation,
                payload=p,
                device=device,
                resolved=resolved,
                upload_path=upload_path,
                upload_record=upload_record,
                dataset_context=context,
                report_context=report_context,
                source_context=source_context,
                scene_context=scene_context,
            )
            thread = threading.Thread(target=self.execute, args=(job, request, warnings), daemon=True)
            self.threads.append(thread)
            thread.start()
        return dict(status="accepted", job_id=job["id"], job_status=job["status"])

    def execute(self, job, request, warnings):
        try:
            attempts = []
            retries = request["payload"]["execution"]["max_retries"]
            for index in range(retries + 1):
                attempt_id = job["attempt_id"] if index == 0 else uid("attempt")
                directory = self.store.root / "attempts" / attempt_id
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "request.json").write_text(canonical(request), encoding="utf-8")
                attempts.append(dict(id=attempt_id, index=index, started_at=now(), status="running"))
                with self.lock:
                    cancelled = self.store.job(job["id"])["status"] == "cancel_requested"
                    if cancelled:
                        (directory / "cancel").touch()
                    self.store.update_job(
                        job["id"],
                        stage="Повторная попытка" if index else "Вычисление",
                        status="cancel_requested" if cancelled else "running",
                        backend=request["device"],
                        warnings=warnings,
                        started_at=now(),
                        attempt_id=attempt_id,
                        attempts=attempts,
                    )
                future = self.client.submit(
                    run_isolated,
                    str(directory),
                    request["payload"]["execution"]["timeout_seconds"],
                    pure=False,
                    resources={"GPU": 1} if request["device"] == "cuda" else {},
                )
                result = future.result()
                attempts[-1].update(
                    status="compute_succeeded" if result["ok"] else "failed",
                    completed_at=now(),
                    error=result.get("error"),
                )
                self.store.update_job(job["id"], attempts=attempts)
                retry_code = result.get("error", {}).get("code")
                cancelled = self.store.job(job["id"])["status"] == "cancel_requested"
                if (
                    result["ok"]
                    or cancelled
                    or retry_code not in ("WORKER_CRASH", "TIMEOUT", "COMPUTE_FAILED")
                ):
                    break
            current = self.store.job(job["id"])
            if current["status"] == "cancel_requested" or result.get("error", {}).get("code") == "CANCELLED":
                self.store.update_job(job["id"], status="cancelled", stage="Отменено", completed_at=now())
            elif result["ok"]:
                for path in result["files"].values():
                    require(
                        Path(path).resolve().is_relative_to(directory / "output")
                        or path == request.get("upload_path"),
                        "INVALID_OUTPUT",
                        "Worker output вне разрешённого каталога",
                    )
                # Publication after integrity checks; cancellation cannot yield a succeeded job.
                with self.lock:
                    if self.store.job(job["id"])["status"] == "cancel_requested":
                        self.store.update_job(job["id"], status="cancelled", stage="Отменено")
                        return
                    if request.get("source_context"):
                        from opensubsurface.adapters.large_grid import check_source
                        from opensubsurface.adapters.local_sources import LocalSources

                        context = request["source_context"]
                        require(
                            LocalSources(self.store).get(context["source"]["id"]) == context["source"],
                            "SOURCE_CHANGED",
                            "Источник изменён или отозван во время импорта",
                        )
                        check_source(context)
                    params = dict(request["payload"], environment=result["environment"])
                    if request.get("upload_record"):
                        params["input_file"] = request["upload_record"]
                    sources = [ref(o) for o in request["resolved"].values()]
                    previous = request["payload"].get("previous")
                    obj = self.store.publish(
                        job["project_id"],
                        result["kind"],
                        result["summary"],
                        result["files"],
                        params,
                        sources,
                        object_id=previous["id"] if previous else None,
                    )
                    self.store.update_job(
                        job["id"],
                        status="succeeded",
                        stage="Завершено",
                        result=ref(obj),
                        elapsed_seconds=result["elapsed_seconds"],
                        completed_at=now(),
                    )
            else:
                diagnostics = None
                if result.get("diagnostics"):
                    for path in result["diagnostics"].values():
                        require(
                            Path(path).resolve().is_relative_to(directory / "output"),
                            "INVALID_OUTPUT",
                            "Неверный diagnostic output",
                        )
                    diagnostic = self.store.publish(
                        job["project_id"],
                        "job_diagnostics",
                        dict(error=result["error"]),
                        result["diagnostics"],
                        parameters=dict(job_id=job["id"], operation=job["operation"]),
                        sources=[ref(o) for o in request["resolved"].values()],
                    )
                    diagnostics = ref(diagnostic)
                self.store.update_job(
                    job["id"],
                    status="failed",
                    stage="Ошибка",
                    error=result["error"],
                    result=diagnostics,
                    completed_at=now(),
                )
        except Exception as e:
            self.store.update_job(
                job["id"],
                status="failed",
                stage="Ошибка control plane",
                error=e.as_dict()
                if isinstance(e, DomainError)
                else dict(code="EXECUTOR_FAILED", message="Ошибка исполнения: " + type(e).__name__),
                completed_at=now(),
            )

    def cancel(self, job_id):
        with self.lock:
            job = self.store.job(job_id)
            if job["status"] in TERMINAL:
                return job
            directory = self.store.root / "attempts" / job["attempt_id"]
            directory.mkdir(exist_ok=True, parents=True)
            (directory / "cancel").touch()
            for child_id in job.get("child_jobs", []):
                self.cancel(child_id)
            return self.store.update_job(job_id, status="cancel_requested", stage="Отмена запрошена")

    def wait(self, submission, timeout=3600):
        if "job_id" not in submission:
            return submission
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            job = self.store.job(submission["job_id"])
            if job["status"] in TERMINAL:
                if job["status"] == "succeeded":
                    return self.store.object(job["project_id"], job["result"])
                error = job["error"] or dict(code="CANCELLED", message="Задание отменено или прервано")
                raise DomainError(error["code"], error["message"])
            time.sleep(0.1)
        raise DomainError("TIMEOUT", "Истёк срок ожидания")

    def submit_orchestrator(self, operation, payload):
        self.start()
        if operation == "workflow_run":
            workflow = self.store.object(payload["project_id"], payload["workflow"])
            require(workflow["kind"] == "workflow", "TYPE_MISMATCH", "Требуется workflow")
            engine.validate(workflow["parameters"]["nodes"])
            nodes = workflow["parameters"]["nodes"]
            future_refs = {node["id"]: dict(id="pending-" + node["id"], revision=1) for node in nodes}
            future_ids = {value["id"] for value in future_refs.values()}
            for node in nodes:
                args = engine.resolve(node["arguments"], future_refs, payload["parameters"])
                require(
                    args.get("project_id") == payload["project_id"],
                    "PERMISSION_DENIED",
                    "Workflow не меняет проект",
                )
                typed = OPERATION_SCHEMAS[node["operation"]].model_validate(args).model_dump(mode="json")
                self.preflight(node["operation"], typed)
                for port, kind in engine.PORT_KINDS.items():
                    value = typed.get(port)
                    if value and value["id"] not in future_ids:
                        obj = self.store.object(payload["project_id"], value)
                        require(obj["kind"] == kind, "TYPE_MISMATCH", f"Неверный тип входного порта {port}")
                for artifact_ref in engine.artifact_refs(typed):
                    if artifact_ref["id"] not in future_ids:
                        self.store.object(payload["project_id"], artifact_ref)

        plan = None
        if operation == "ensemble_run":
            from opensubsurface.workflows.ensembles import build_plan

            plan = build_plan(self, payload)
            if payload.get("resume_ensemble"):
                previous = self.store.object(payload["project_id"], payload["resume_ensemble"])
                require(previous["kind"] == "ensemble", "TYPE_MISMATCH", "resume_ensemble требует ensemble")
        job, created = self.store.put_job(operation, payload)
        if created:
            if plan is not None:
                job = self.store.update_job(job["id"], resolved_plan=plan)
            thread = threading.Thread(target=self.orchestrate, args=(job,), daemon=True)
            self.threads.append(thread)
            thread.start()
        return dict(status="accepted", job_id=job["id"], job_status=job["status"])

    def orchestrate(self, job):
        p, project_id = job["payload"], job["project_id"]
        children = []
        records = {}
        try:
            self.store.update_job(job["id"], status="running", stage="Проверка графа", child_jobs=children)
            if job["operation"] == "ensemble_run":
                from opensubsurface.workflows.ensembles import execute

                obj = execute(self, job)
                if obj is None:
                    return
            else:
                workflow = self.store.object(project_id, p["workflow"])
                nodes = {n["id"]: n for n in workflow["parameters"]["nodes"]}
                order = engine.validate(list(nodes.values()))
                outputs, records = {}, {}
                previous = {}
                if p.get("resume_run"):
                    old = self.store.object(project_id, p["resume_run"])
                    require(
                        old["kind"] == "workflow_run", "TYPE_MISMATCH", "resume_run должен быть workflow run"
                    )
                    previous = old["summary"]["nodes"]
                # Each ready frontier submitted before waiting: explicit fan-out, then fan-in.
                remaining = set(order)
                runtime = fingerprint()
                while remaining:
                    ready = [
                        n
                        for n in order
                        if n in remaining
                        and (set(nodes[n]["depends_on"]) | set(engine.references(nodes[n]["arguments"])))
                        <= set(outputs)
                    ]
                    require(bool(ready), "INVALID_WORKFLOW", "Не удалось разрешить зависимости")
                    pending = []
                    for name in ready:
                        self.check_cancel(job["id"])
                        node = nodes[name]
                        args = engine.resolve(node["arguments"], outputs, p["parameters"], run_id=job["id"])
                        require(
                            args.get("project_id") == project_id,
                            "PERMISSION_DENIED",
                            "Workflow не меняет проект",
                        )
                        typed = (
                            OPERATION_SCHEMAS[node["operation"]].model_validate(args).model_dump(mode="json")
                        )
                        resolved = self.resolve_inputs(node["operation"], typed)
                        h = digest(
                            dict(
                                operation=node["operation"],
                                args=typed,
                                inputs={k: v["content_hash"] for k, v in resolved.items()},
                                app="0.2.0.dev1",
                                runtime=runtime,
                            )
                        )
                        old = previous.get(name, {})
                        if old.get("hash") == h and old.get("result"):
                            cached = self.store.object(project_id, old["result"])
                            outputs[name] = ref(cached)
                            records[name] = dict(hash=h, result=ref(cached), reused=True)
                            remaining.remove(name)
                        else:
                            submission = self.invoke(node["operation"], typed)
                            if submission.get("job_id"):
                                children.append(submission["job_id"])
                                self.store.update_job(job["id"], child_jobs=children, stage="Узел " + name)
                            pending.append((name, h, submission))
                    for name, h, submission in pending:
                        self.check_cancel(job["id"])
                        result = self.wait(submission)
                        outputs[name] = ref(result)
                        records[name] = dict(hash=h, result=ref(result), reused=False)
                        remaining.remove(name)
                    self.store.update_job(job["id"], node_results=records)
                gate = workflow["parameters"].get("result_gate_node")
                validation_failed = False
                if gate:
                    gate_obj = self.store.object(project_id, outputs[gate])
                    validation_failed = (
                        gate_obj["kind"] != "calculation_report"
                        or gate_obj["summary"].get("validation_status") != "PASS"
                    )
                obj = self.store.publish(
                    project_id,
                    "workflow_run",
                    dict(
                        nodes=records,
                        plan_hash=digest(workflow["parameters"]),
                        compute_status="validation_failed" if validation_failed else "completed",
                        cleanup_status="not_applicable",
                    ),
                    parameters=p,
                    sources=[p["workflow"]],
                )
            self.check_cancel(job["id"])
            validation_failed = obj["summary"].get("compute_status") == "validation_failed"
            partial = obj["summary"].get("compute_status") == "partial_failure" or validation_failed
            self.store.update_job(
                job["id"],
                status="failed" if partial else "succeeded",
                stage="Часть cases завершилась с ошибкой" if partial else "Завершено",
                result=ref(obj),
                error=dict(
                    code="VALIDATION_FAILED" if validation_failed else "PARTIAL_FAILURE",
                    message="Проверьте отчёт валидации"
                    if validation_failed
                    else "Проверьте статусы всех child cases",
                )
                if partial
                else None,
                completed_at=now(),
            )
        except Exception as e:
            cancelled = self.store.job(job["id"])["status"] == "cancel_requested"
            partial_ref = None
            if records and job["operation"] == "workflow_run":
                partial_obj = self.store.publish(
                    project_id,
                    "workflow_run",
                    dict(
                        nodes=records,
                        compute_status="cancelled" if cancelled else "failed",
                        cleanup_status="not_applicable",
                    ),
                    parameters=p,
                    sources=[p["workflow"]],
                )
                partial_ref = ref(partial_obj)
            self.store.update_job(
                job["id"],
                status="cancelled" if cancelled else "failed",
                stage="Прервано",
                result=partial_ref,
                error=e.as_dict()
                if isinstance(e, DomainError)
                else dict(code="WORKFLOW_FAILED", message=type(e).__name__),
            )

    def check_cancel(self, job_id):
        require(self.store.job(job_id)["status"] != "cancel_requested", "CANCELLED", "Workflow отменён")

    def compare(self, operation, p):
        from opensubsurface.domain.numerics import quantiles
        from opensubsurface.domain.results import analyze_cases

        cases = []
        sources = list(p["results"])
        if p.get("ensemble"):
            require(
                operation == "ensemble_compare",
                "TYPE_MISMATCH",
                "ensemble ref допустим только для ensemble_compare",
            )
            ensemble = self.store.object(p["project_id"], p["ensemble"])
            require(ensemble["kind"] == "ensemble", "TYPE_MISMATCH", "Требуется ensemble artifact")
            sources = [p["ensemble"]]
            for row in ensemble["summary"]["rows"]:
                if row["status"] == "succeeded" and row.get("result"):
                    obj = self.store.object(p["project_id"], row["result"])
                    cases.append(self.result_case(obj))
                else:
                    cases.append(
                        dict(
                            id=row.get("job_id") or digest(row)[:16],
                            status=row["status"],
                            error=row.get("error"),
                        )
                    )
            objects = []
        else:
            objects = [self.store.object(p["project_id"], r) for r in p["results"]]
            require(
                len({o["kind"] for o in objects}) == 1, "TYPE_MISMATCH", "Нельзя смешивать типы результатов"
            )
        if objects and objects[0]["kind"] == "volumetrics":
            require(
                p["metric"] in ("auto", "STOIIP") and operation != "development_rank",
                "TYPE_MISMATCH",
                "Для статических объёмов метрика STOIIP",
            )
            rows = [dict(result=ref(o), value=o["summary"]["values"]["STOIIP"]) for o in objects]
            summary = dict(
                rows=rows,
                statistics=quantiles([r["value"] for r in rows]),
                ranking=sorted(rows, key=lambda r: r["value"], reverse=True),
                metric="STOIIP",
                unit="standard_m3",
                claim="Ранжирование явных вариантов; не глобальный оптимум",
            )
            files = None
        else:
            cases.extend(self.result_case(obj) for obj in objects)
            summary = analyze_cases(
                cases,
                metric="FOPT" if p["metric"] == "auto" else p["metric"],
                dates=p.get("dates"),
                report_at=p.get("report_at"),
                allow_partial=p["allow_partial"],
                direction=p.get("direction", "maximize"),
                constraints=p.get("constraints"),
            )
            # Store potentially large series separately; tool response contains only compact report metadata.
            import tempfile

            with tempfile.TemporaryDirectory(dir=self.store.root) as temp:
                path = Path(temp) / "analysis.json"
                path.write_text(canonical(summary), encoding="utf-8")
                from opensubsurface.adapters.results import write_analysis_csv

                csv_path = Path(temp) / "analysis.csv"
                write_analysis_csv(summary, csv_path)
                compact = {k: v for k, v in summary.items() if k not in ("series", "pointwise", "dates")}
                compact["report_date_count"] = len(summary["dates"])
                compact["report_date_range"] = (
                    [summary["dates"][0], summary["dates"][-1]] if summary["dates"] else []
                )
                compact["pointwise_vectors"] = list(summary["pointwise"])
                return self.store.publish(
                    p["project_id"],
                    "comparison",
                    compact,
                    {"analysis.json": path, "analysis.csv": csv_path},
                    parameters=p,
                    sources=sources,
                )
        return self.store.publish(
            p["project_id"], "comparison", summary, files, parameters=p, sources=sources
        )

    def result_case(self, obj):
        require(obj["kind"] == "simulation_result", "TYPE_MISMATCH", "Требуется simulation_result artifact")
        require("series.json" in obj["files"], "INVALID_RESULTS", "Отсутствует нормализованный series.json")
        raw = json.loads(self.store.path(obj, "series.json").read_text(encoding="utf-8"))
        return dict(id=obj["id"] + ":r" + str(obj["revision"]), status="succeeded", series=raw)

    def demo(self):
        project = self.invoke(
            "project_create",
            dict(name="Демонстрационное месторождение", crs="LOCAL_METRIC", vertical_datum="SYNTHETIC_MSL"),
        )
        pid = project["id"]
        model = self.wait(self.invoke("model_build", dict(project_id=pid, horizontal_assumption=True)))
        props = self.wait(
            self.invoke(
                "properties_assign",
                dict(
                    project_id=pid,
                    model=ref(model),
                    zones={"1": dict(phi=0.2, ntg=0.8, sw=0.25, permeability_md=100)},
                ),
            )
        )
        result = self.wait(
            self.invoke(
                "volumetrics_calculate",
                dict(project_id=pid, properties=ref(props), contact_z_m=-1020, bo=1.2),
            )
        )
        return dict(project=project, model=ref(model), properties=ref(props), volumetrics=result)
