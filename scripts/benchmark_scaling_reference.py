"""Identical before/after workloads; PYTHONPATH selects the measured checkout."""

import argparse
import cProfile
import json
import platform
import pstats
import shutil
import tempfile
import threading
import time
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import psutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["synthetic", "norne"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    if args.device == "cuda" and args.kind != "norne":
        parser.error("CUDA is only for the Norne production kernel; the independent integral stays CPU")
    from opensubsurface.adapters.regional_volumes import evaluate
    from opensubsurface.calculations.cornerpoint_reference import integral

    peak = [psutil.Process().memory_info().rss]
    stopped = threading.Event()

    def sample():
        while not stopped.wait(0.1):
            try:
                root = psutil.Process()
                peak[0] = max(
                    peak[0], sum(p.memory_info().rss for p in [root, *root.children(recursive=True)])
                )
            except psutil.Error:
                pass

    with tempfile.TemporaryDirectory(prefix="kanysh-reference-") as temporary:
        if args.kind == "synthetic":
            rng = np.random.default_rng(818)
            offsets = np.array(
                [
                    [0, 0, 0],
                    [10, 0, 0],
                    [0, 20, 0],
                    [10, 20, 0],
                    [0, 0, -5],
                    [10, 0, -5],
                    [0, 20, -5],
                    [10, 20, -5],
                ]
            )
            c = np.zeros((113000, 8, 3)) + offsets
            c[:, :, 2] += rng.choice([0.0, -10.0], size=113000, p=[0.1, 0.9])[:, None]

            def function():
                return integral(c, -2.5)
        else:
            with ZipFile(
                Path(__file__).resolve().parents[1] / "src/opensubsurface/data/norne/project.zip"
            ) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                obj = next(o for o in manifest["objects"] if o["kind"] == "properties")
                path = Path(temporary) / "grid.zip"
                with archive.open("blobs/" + obj["files"]["grid.zip"]) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)
            obj["paths"] = {"grid.zip": str(path)}
            p = dict(
                region_field="zones",
                scenarios=[
                    dict(
                        name="OWC-2693.3",
                        regions=[
                            dict(region_id=r, owc_z_m=-2693.3, bo=1.2, sg_in_oil_zone=0.0)
                            for r in obj["summary"]["zone_ids"]
                        ],
                    )
                ],
                geometry_policy="exclude_flagged",
                parameters_confirmed=True,
                assumptions=["Bundled public Norne geometry and explicitly declared demo properties"],
                polygon_ids=[],
                polygon_hole_ids=[],
                execution=dict(max_workers=args.workers),
            )

            def function():
                return evaluate(obj, p)

        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        started = time.perf_counter()
        profile = cProfile.Profile() if args.profile else None
        if profile:
            profile.enable()
        token = None
        if args.device == "cuda":
            from opensubsurface.execution.blocks import settings

            token = settings.set(dict(resolved_device="cuda", max_workers=args.workers))
        try:
            result = function()
        finally:
            if token is not None:
                settings.reset(token)
        if profile:
            profile.disable()
        elapsed = time.perf_counter() - started
        stopped.set()
        monitor.join()
        report = dict(
            status="PASS",
            workload=args.kind,
            seconds=elapsed,
            peak_process_tree_rss_bytes=max(peak[0], psutil.Process().memory_info().rss),
            workers=args.workers,
            device=args.device,
            hardware=dict(
                platform=platform.platform(),
                logical_cores=psutil.cpu_count(),
                ram_bytes=psutil.virtual_memory().total,
            ),
        )
        if profile:
            stats = pstats.Stats(profile)
            report["profile_top_cumulative"] = [
                dict(function=f"{Path(key[0]).name}:{key[1]}:{key[2]}", calls=v[1], cumulative_seconds=v[3])
                for key, v in sorted(stats.stats.items(), key=lambda x: x[1][3], reverse=True)[:15]
            ]
        if args.kind == "synthetic":
            report.update(cells=113000, total_m3=float(result.sum()))
        else:
            report.update(
                cells=obj["summary"]["cells"],
                active_cells=obj["summary"]["active_cells"],
                result_status=result["status"],
                validation_status=result["validation_status"],
                exclusions=result["geometry_exclusions"],
                totals=result["tables"]["scenarios"],
            )
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
