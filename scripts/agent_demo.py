"""Real MCP SDK client/control calculation. Not a test of ChatGPT/Claude model reasoning."""

import argparse
import asyncio
import base64
import json
import os
import time
import zipfile
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def demo(args):
    token = os.environ.get("OPENSUBSURFACE_TOKEN")
    headers = {"Authorization": "Bearer " + token} if token else {}
    async with httpx.AsyncClient(timeout=60, headers=headers) as http:
        async with streamable_http_client(args.url.rstrip("/") + "/", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(operation, **request):
                    result = await session.call_tool(operation, arguments=dict(request=request))
                    if result.isError:
                        raise RuntimeError(str(result.content))
                    payload = json.loads(result.content[0].text)
                    if "error" in payload:
                        raise RuntimeError(json.dumps(payload["error"], ensure_ascii=False))
                    return payload["result"]

                project = await call(
                    "project_create",
                    name="Agent control — SYNTHETIC",
                    crs="LOCAL_METRIC",
                    vertical_datum="SYNTHETIC_MSL",
                )
                pid = project["id"]
                listing = await call("source_scan", source_id=args.source_id)
                files = {entry["path"]: entry for entry in listing["entries"]}
                inputs = []
                for filename, role in [("surfaces.csv", "surfaces"), ("orientations.csv", "orientations")]:
                    if filename not in files:
                        raise RuntimeError("Register examples/agent-demo as source; missing " + filename)
                    entry = files[filename]
                    info = await call(
                        "source_inspect",
                        source_id=args.source_id,
                        path=filename,
                        file_revision=entry["file_revision"],
                    )
                    if role not in info["candidate_kinds"]:
                        raise RuntimeError("Unexpected control CSV schema")
                    inputs.append(
                        dict(
                            kind=role,
                            source_id=args.source_id,
                            path=filename,
                            file_revision=entry["file_revision"],
                            units=dict(x="m", y="m", z="m"),
                        )
                    )
                plan = await call(
                    "calculation_plan",
                    project_id=pid,
                    name="Synthetic GemPy → volumes → validation",
                    method="gempy",
                    horizontal_assumption=False,
                    inputs=inputs,
                    grid=dict(shape=[3, 4, 8], extent=[0, 1000, 0, 1000, -1040, -1000]),
                    zones={
                        "1": dict(phi=0, ntg=0, sw=1, permeability_md=0),
                        "2": dict(phi=0.2, ntg=0.8, sw=0.25, permeability_md=100),
                    },
                    zone_ids=[2],
                    bo=1.2,
                    contacts=[
                        dict(name="full", z_m=-1040),
                        dict(name="half", z_m=-1030),
                        dict(name="dry", z_m=-1020),
                    ],
                    assumptions=[
                        "Synthetic analytical control, not field data or a production forecast",
                        "Horizontal horizon, homogeneous reservoir below it, constant Bo and horizontal OWC",
                    ],
                    uncertainty=dict(
                        contact_name="full",
                        distributions=dict(phi=dict(kind="uniform", low=0.15, high=0.25)),
                        count=30,
                        seed=42,
                    ),
                )
                plan_ref = dict(id=plan["id"], revision=plan["revision"])
                await call("plan_validate", project_id=pid, plan=plan_ref)
                submitted = await call("calculation_run", project_id=pid, plan=plan_ref)
                deadline = time.monotonic() + 240
                while True:
                    status = await call("calculation_status", project_id=pid, run_id=submitted["run_id"])
                    if status["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError(
                            "Still running; query calculation_status with run_id=" + submitted["run_id"]
                        )
                    await asyncio.sleep(0.5)
                if not status.get("report"):
                    raise RuntimeError(json.dumps(status, ensure_ascii=False))
                report = status["report"]
                args.output.mkdir(parents=True, exist_ok=True)
                for filename in ("report.html", "report.md", "report.json", "volumes.png", "volumes.csv"):
                    uri = f"opensubsurface://projects/{pid}/artifacts/{report['id']}/{report['revision']}/{filename}"
                    resource = (await session.read_resource(uri)).contents[0]
                    data = (
                        base64.b64decode(resource.blob)
                        if hasattr(resource, "blob")
                        else resource.text.encode()
                    )
                    (args.output / filename).write_bytes(data)
                (args.output / "run.json").write_text(
                    json.dumps(dict(project_id=pid, **status), ensure_ascii=False, indent=2)
                )
                with zipfile.ZipFile(args.output / "report.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
                    for filename in (
                        "report.html",
                        "report.md",
                        "report.json",
                        "volumes.png",
                        "volumes.csv",
                        "run.json",
                    ):
                        bundle.write(args.output / filename, filename)
                evidence = json.loads((args.output / "report.json").read_text())
                actual = [row["STOIIP"] for row in evidence["contacts"]]
                ok = (
                    status["status"] == "succeeded"
                    and evidence["validation_status"] == "PASS"
                    and all(abs(a - b) <= 1e-6 for a, b in zip(actual, [2e6, 1e6, 0]))
                    and len(actual) == 3
                )
                print(
                    json.dumps(
                        dict(
                            run_id=submitted["run_id"],
                            validation=evidence["validation_status"],
                            stoiip_standard_m3=actual,
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
    parser.add_argument("--url", default="http://127.0.0.1:8765/mcp/")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output", type=Path, default=Path("examples/agent-demo/generated"))
    asyncio.run(demo(parser.parse_args()))
