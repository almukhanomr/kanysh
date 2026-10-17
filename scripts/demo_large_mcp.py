"""Actual HTTP MCP control for examples/cartesian-grdecl; synthetic fixture, not external LLM QA."""

import argparse
import asyncio
import base64
import json
import math
import os
import zipfile
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main(args):
    token = os.environ.get("OPENSUBSURFACE_TOKEN")
    async with httpx.AsyncClient(
        timeout=60, headers={"Authorization": "Bearer " + token} if token else {}
    ) as http:
        async with streamable_http_client(args.url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(operation, **request):
                    response = await session.call_tool(operation, arguments=dict(request=request))
                    if response.isError:
                        raise RuntimeError(str(response.content))
                    payload = json.loads(response.content[0].text)
                    if "error" in payload:
                        raise RuntimeError(str(payload["error"]))
                    return payload["result"]

                files = (await call("source_scan", source_id=args.source_id))["entries"]
                entry = next(e for e in files if e["path"] == "model.json")
                source = dict(
                    source_id=args.source_id, path="model.json", file_revision=entry["file_revision"]
                )
                info = await call("source_inspect", **source)
                manifest = info["manifest"]
                if (
                    manifest["grid"] != {"shape": [13, 17, 19], "extent": [0.0, 13.0, 0.0, 17.0, -19.0, 0.0]}
                    or manifest["vertical_datum"] != "SYNTHETIC_MSL"
                ):
                    raise RuntimeError("Use only examples/cartesian-grdecl synthetic control")
                pid = (
                    await call(
                        "project_create",
                        name="GRDECL chunked MCP — SYNTHETIC",
                        crs=manifest["crs"],
                        vertical_datum=manifest["vertical_datum"],
                    )
                )["id"]
                submitted = await call("grid_import", project_id=pid, **source, block_cells=1024)
                for _ in range(240):
                    job = await call("job_status", job_id=submitted["job_id"])
                    if job["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
                        break
                    await asyncio.sleep(0.5)
                if job["status"] != "succeeded":
                    raise RuntimeError(str(job))
                plan = await call(
                    "calculation_plan",
                    project_id=pid,
                    properties=job["result"],
                    zone_ids=[1],
                    bo=1.2,
                    contacts=[
                        dict(name="full", z_m=-19),
                        dict(name="partial", z_m=-10),
                        dict(name="dry", z_m=0),
                    ],
                    assumptions=[
                        "Synthetic uniform Cartesian geometry, exported GRDECL property controls",
                        "Homogeneous phi=.2 NTG=.8 Sw=.25 Bo=1.2; not field data or a forecast",
                    ],
                    uncertainty=dict(
                        contact_name="full",
                        distributions=dict(phi=dict(kind="uniform", low=0.15, high=0.25)),
                        count=5,
                        seed=42,
                    ),
                )
                pref = dict(id=plan["id"], revision=plan["revision"])
                await call("plan_validate", project_id=pid, plan=pref)
                submitted = await call("calculation_run", project_id=pid, plan=pref)
                for _ in range(240):
                    status = await call("calculation_status", project_id=pid, run_id=submitted["run_id"])
                    if status["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
                        break
                    await asyncio.sleep(0.5)
                if status["status"] != "succeeded":
                    raise RuntimeError(str(status))
                report = status["report"]
                args.output.mkdir(exist_ok=True, parents=True)
                for name in ("report.html", "report.md", "report.json", "volumes.csv", "volumes.png"):
                    uri = f"opensubsurface://projects/{pid}/artifacts/{report['id']}/{report['revision']}/{name}"
                    resource = (await session.read_resource(uri)).contents[0]
                    (args.output / name).write_bytes(base64.b64decode(resource.blob))
                (args.output / "run.json").write_text(
                    json.dumps(dict(project_id=pid, **status), ensure_ascii=False, indent=2)
                )
                result = json.loads((args.output / "report.json").read_text())
                actual = [row["STOIIP"] for row in result["contacts"]]
                ok = (
                    result["validation_status"] == "PASS"
                    and len(actual) == 3
                    and all(
                        math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8)
                        for a, b in zip(actual, [419.9, 221, 0])
                    )
                )
                with zipfile.ZipFile(args.output / "report.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
                    for name in (
                        "report.html",
                        "report.md",
                        "report.json",
                        "volumes.csv",
                        "volumes.png",
                        "run.json",
                    ):
                        bundle.write(args.output / name, name)
                print(
                    json.dumps(
                        dict(
                            run_id=status["run_id"],
                            stoiip_standard_m3=actual,
                            validation=result["validation_status"],
                            analytical_control="PASS" if ok else "FAIL",
                            output=str(args.output.resolve()),
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                if not ok:
                    raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8765/mcp/")
    parser.add_argument("--output", type=Path, default=Path("examples/cartesian-grdecl/generated"))
    asyncio.run(main(parser.parse_args()))
