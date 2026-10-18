"""Cross-platform stage timings, peak process-tree RSS and cProfile evidence.

Example: python scripts/benchmark_scaling.py --sizes 10000000 50000000 100000000
Each size runs in a fresh subprocess. JSON is checkpointed after every stage;
missing stages remain NOT RUN. The same script can run against a baseline
checkout by setting PYTHONPATH to that checkout's src directory.
"""

import argparse
import copy
import cProfile
import datetime
import json
import os
import platform
import pstats
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import psutil
from generate_scaling_model import SHAPES, generate

STAGES = (
    "generate",
    "import",
    "model_qc",
    "regional_volumes_1",
    "regional_volumes_5",
    "tornado_4",
    "calculation_run",
    "scene_export",
)


def peak_rss():
    try:
        processes = [psutil.Process(), *psutil.Process().children(recursive=True)]
        return sum(p.memory_info().rss for p in processes if p.is_running())
    except psutil.Error:
        return 0


def worker(args):
    import hashlib

    import opensubsurface
    from opensubsurface.adapters.eclipse_import import import_deck
    from opensubsurface.adapters.local_sources import LocalSources, path_revision
    from opensubsurface.adapters.model_qc import run as qc
    from opensubsurface.adapters.regional_volumes import evaluate
    from opensubsurface.adapters.sensitivity import tornado
    from opensubsurface.errors import DomainError
    from opensubsurface.service import Service

    code = hashlib.sha256()
    source_root = Path(opensubsurface.__file__).parent
    for source_file in sorted(source_root.rglob("*.py")):
        code.update(str(source_file.relative_to(source_root)).encode())
        code.update(source_file.read_bytes())
    report = dict(
        phase=args.phase,
        started_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        cells=args.worker,
        status="INCOMPLETE",
        code_sha256=code.hexdigest(),
        requested_max_workers=args.workers,
        stage_selection=args.stages,
        source_generator_sha256=hashlib.sha256(Path(generate.__code__.co_filename).read_bytes()).hexdigest(),
        rss_sampling_interval_seconds=0.1,
        profiler_scope="coordinator process; process worker wall includes children",
        hardware=dict(
            platform=platform.platform(),
            logical_cores=psutil.cpu_count(),
            physical_cores=psutil.cpu_count(logical=False),
            ram_bytes=psutil.virtual_memory().total,
        ),
        stages={stage: dict(status="NOT RUN", reason="Stage not reached") for stage in STAGES},
    )
    output = args.output.resolve()

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        for attempt in range(8):
            try:
                os.replace(temporary, output)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.02 * (attempt + 1))

    save()

    def stage(name, function):
        if name not in args.stages:
            report["stages"][name] = dict(
                status="NOT RUN", reason="Explicit --stages selection; no timing inferred"
            )
            save()
            return None
        stop = threading.Event()
        peak = [peak_rss()]

        def sample():
            while not stop.wait(0.1):
                peak[0] = max(peak[0], peak_rss())

        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        started = time.perf_counter()
        profile = cProfile.Profile() if args.profile else None
        if profile:
            profile.enable()
        try:
            value = function()
            record = dict(status="PASS")
            if isinstance(value, dict):
                record["result_status"] = value.get("status", value.get("qc_status"))
                record["validation_status"] = value.get("validation_status")
                if value.get("validation_status") == "FAIL":
                    record["status"] = "FAIL"
        except Exception as error:
            value = None
            record = dict(
                status="NOT RUN"
                if isinstance(error, DomainError)
                and error.code in {"INSUFFICIENT_MEMORY", "INSUFFICIENT_DISK"}
                else "FAIL",
                error=error.as_dict()
                if isinstance(error, DomainError)
                else dict(type=type(error).__name__, message=str(error)),
            )
        finally:
            if profile:
                profile.disable()
                profile_path = (
                    output.parent.parent / ".data" / "scaling-profiles" / (output.stem + "-" + name + ".prof")
                )
                profile_path.parent.mkdir(parents=True, exist_ok=True)
                profile.dump_stats(str(profile_path))
                stats = pstats.Stats(profile)
                record["profile_top_cumulative"] = [
                    dict(
                        function=f"{Path(key[0]).name}:{key[1]}:{key[2]}", calls=v[1], cumulative_seconds=v[3]
                    )
                    for key, v in sorted(stats.stats.items(), key=lambda x: x[1][3], reverse=True)[:12]
                ]
            stop.set()
            monitor.join()
            record.update(
                seconds=time.perf_counter() - started, peak_process_tree_rss_bytes=max(peak[0], peak_rss())
            )
            report["stages"][name] = record
            save()
            print(
                f"{args.worker} {name}: {record['status']} {record['seconds']:.2f}s RSS {record['peak_process_tree_rss_bytes'] / 1024**3:.2f}GiB",
                flush=True,
            )
        return value

    with tempfile.TemporaryDirectory(prefix="kanysh-scaling-", dir=args.work_dir) as temporary:
        base = Path(temporary)
        shape = SHAPES.get(args.worker, (100, max(1, args.worker // 1000), 10))
        generated = stage("generate", lambda: generate(base / "source", shape))
        if not generated:
            return
        path, analytic = generated
        report["input_bytes"] = path.stat().st_size
        report["materialized_corner_bytes"] = analytic["cells"] * 192
        report["analytic"] = analytic
        service = Service(base / "home")
        try:
            pid = service.invoke(
                "project_create", dict(name="Scaling benchmark", vertical_datum="SYNTHETIC")
            )["id"]
            source = LocalSources(service.store).register("Generated scaling model", path.parent)
            out = base / "import"
            out.mkdir()
            p = dict(
                path=path.name,
                file_revision=path_revision(path),
                length_unit="m",
                z_direction="down",
                defaults={},
                region_field="EQLNUM",
                crs="LOCAL_METRIC",
                vertical_datum="SYNTHETIC",
                assumptions=["Explicit generated synthetic fields; see analytic.json"],
                block_cells=16384,
            )
            imported = stage("import", lambda: import_deck(dict(source=source), p, out))
            if not imported:
                return
            _, summary, files = imported
            obj = dict(
                id="benchmark",
                revision=1,
                content_hash="0" * 64,
                kind="properties",
                summary=summary,
                paths={k: str(v) for k, v in files.items()},
            )
            execution = dict(max_workers=args.workers)
            qc_out = base / "qc"
            qc_out.mkdir()
            stage(
                "model_qc",
                lambda: qc(
                    obj,
                    dict(
                        region_field="EQLNUM",
                        small_cluster_cells=1,
                        max_examples=100,
                        assumptions=p["assumptions"],
                        execution=execution,
                    ),
                    qc_out,
                ),
            )
            regions = [dict(region_id=r, owc_z_m=-22.5, bo=1.2, sg_in_oil_zone=0.0) for r in range(1, 6)]
            params = dict(
                region_field="EQLNUM",
                scenarios=[dict(name="base", regions=regions)],
                geometry_policy="exclude_flagged",
                parameters_confirmed=True,
                assumptions=p["assumptions"],
                polygon_ids=[],
                polygon_hole_ids=[],
                execution=execution,
            )

            def regional(parameters):
                result = evaluate(obj, parameters)
                for row in result["tables"]["regions"]:
                    expected = analytic["expected_regions"][row["region_id"] - 1]
                    for metric in ("GRV", "GRV_oil_interval", "STOIIP"):
                        np.testing.assert_allclose(row[metric], expected[metric], rtol=1e-8, atol=1e-7)
                assert result["geometry_exclusions"]["excluded_cells"] == 3 * len(parameters["scenarios"])
                return result

            stage("regional_volumes_1", lambda: regional(params))
            five = copy.deepcopy(params)
            five["scenarios"] = [dict(name=f"scenario-{i}", regions=regions) for i in range(5)]
            report["five_scenario_scope"] = (
                "Five separately reduced cases with the same OWC/properties; geometry cache reuse. "
                "This does not measure five different contact elevations."
            )
            stage("regional_volumes_5", lambda: regional(five))
            tornado_out = base / "tornado"
            tornado_out.mkdir()
            sensitivity = dict(
                params,
                metric="STOIIP",
                max_cell_scenario_evaluations=10 * analytic["cells"],
                parameters=[
                    dict(region_id=1, field=field, mode="multiplier", low=0.9, high=1.1)
                    for field in ("phi", "ntg", "sw", "bo")
                ],
            )
            stage("tornado_4", lambda: tornado(obj, sensitivity, tornado_out))
            # Use four explicitly selected clean regions in the calculation pipeline.
            # Regional benchmarks above separately exercise all five and explicit exclusions.
            published = service.store.publish(pid, "properties", summary, files)
            ref = dict(id=published["id"], revision=published["revision"])

            def calculation():
                plan = service.invoke(
                    "calculation_plan",
                    dict(
                        project_id=pid,
                        properties=ref,
                        zone_ids=[2, 3, 4, 5],
                        contacts=[dict(name="OWC", z_m=-22.5)],
                        bo=1.2,
                        assumptions=p["assumptions"],
                        execution=execution,
                    ),
                )
                submitted = service.invoke(
                    "calculation_run",
                    dict(project_id=pid, plan=dict(id=plan["id"], revision=plan["revision"])),
                )
                started = time.monotonic()
                while time.monotonic() - started < 7200:
                    status = service.invoke(
                        "calculation_status", dict(project_id=pid, run_id=submitted["job_id"])
                    )
                    if status["status"] in {"completed", "succeeded", "failed", "cancelled"}:
                        if status["status"] in {"failed", "cancelled"}:
                            import shutil

                            logs = Path(".data/scaling-failures") / output.stem
                            logs.mkdir(parents=True, exist_ok=True)
                            for attempt in (service.store.root / "attempts").iterdir():
                                if (attempt / "worker.log").is_file():
                                    shutil.copyfile(attempt / "worker.log", logs / (attempt.name + ".log"))
                            raise RuntimeError(str(status.get("error")))
                        return status
                    time.sleep(0.2)
                raise TimeoutError("calculation_run exceeded 7200s")

            stage("calculation_run", calculation)
            from opensubsurface.adapters.viewer import export_scene
            from opensubsurface.schemas import SceneShow

            scene_out = base / "scene"
            scene_out.mkdir()
            item = SceneShow.model_validate(
                dict(project_id=pid, ref=ref, field="phi", cell_range=[100, 1000])
            ).model_dump(mode="json")
            report["scene_selection"] = dict(
                cell_range=[100, 1000],
                stride=1,
                note="Explicit preview range; calculations always use full selected model",
            )
            stage(
                "scene_export",
                lambda: export_scene(
                    {"model": item}, {"model": obj}, dict(max_cells=1000, max_points=10000), scene_out
                ),
            )
            report["status"] = (
                "PASS" if all(s["status"] == "PASS" for s in report["stages"].values()) else "INCOMPLETE"
            )
            report["rss_limit_bytes"] = psutil.virtual_memory().total // 2
            report["memory_status"] = (
                "PASS"
                if max(s.get("peak_process_tree_rss_bytes", 0) for s in report["stages"].values())
                < report["rss_limit_bytes"]
                else "FAIL"
            )
            save()
        finally:
            service.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=list(SHAPES))
    parser.add_argument("--phase", choices=["before", "after"], default="after")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES))
    parser.add_argument("--worker", type=int)
    args = parser.parse_args()
    if args.output and not args.worker and len(args.sizes) != 1:
        parser.error("--output requires exactly one --sizes value to avoid overwriting reports")
    if args.worker:
        worker(args)
        return
    for cells in args.sizes:
        output = args.output or Path(f"docs/benchmark-scaling-{args.phase}-{cells}.json")
        command = [
            sys.executable,
            __file__,
            "--worker",
            str(cells),
            "--phase",
            args.phase,
            "--output",
            str(output),
        ]
        if args.workers:
            command += ["--workers", str(args.workers)]
        if args.work_dir:
            command += ["--work-dir", str(args.work_dir)]
        if args.profile:
            command += ["--profile"]
        command += ["--stages", *args.stages]
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
