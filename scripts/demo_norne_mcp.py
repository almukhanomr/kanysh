"""Reproduce the publication video through real HTTP MCP, with explicit demo assumptions.

This script is an owner-run demonstration, not an LLM simulation or a new MCP tool.
Fetch full Norne first. The HTTP service must use the --home supplied here.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from norne_demo_support import equil_records
from publication import clean_json

from opensubsurface.adapters.local_sources import LocalSources
from opensubsurface.service import Service

ASSUMPTIONS = [
    "PUBLIC DEMO ONLY: static sensitivity benchmark, not Norne reserves or simulator initialization",
    "Source coordinates are metres and positive depth; canonical Z is negative source depth; CRS/datum are unverified",
    "Explicit demo fluid assumptions: Sw=0.25, Bo=1.2 rm3/sm3, Bg=0.005 rm3/sm3, oil-zone Sg=0, gas-zone So=0.05",
    "Only EQLNUM 1 and 3 are selected for the regional calculation; the original ACTNUM is preserved",
    "QC findings in other regions remain visible; no cells are silently repaired or removed",
]


def reference(obj):
    return {key: obj[key] for key in ("id", "revision")}


async def run(args):
    if not args.accept_demo_assumptions:
        raise SystemExit(
            "Read docs/DEMO.md and explicitly supply --accept-demo-assumptions. No field constants will be inferred."
        )
    root = Path(args.norne_root).resolve()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    # Owner registration is a prerequisite; it is deliberately not an MCP registration tool.
    owner = Service(args.home)
    try:
        source = LocalSources(owner.store).register("Public Norne DATA", root / "full/norne")
    finally:
        owner.close()
    records = {row["region_id"]: row for row in equil_records(root)}
    assert {1, 3} <= records.keys(), "Pinned full Norne EQUIL include is required"
    headers = (
        {"Authorization": "Bearer " + os.environ["OPENSUBSURFACE_TOKEN"]}
        if os.environ.get("OPENSUBSURFACE_TOKEN")
        else {}
    )
    log = []
    async with httpx.AsyncClient(headers=headers, timeout=60, trust_env=False) as http:
        async with streamable_http_client(args.url.rstrip("/") + "/mcp/", http_client=http) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(operation, **request):
                    response = await session.call_tool(operation, arguments=dict(request=request))
                    value = json.loads(response.content[0].text)
                    if response.isError or "error" in value:
                        raise RuntimeError(value)
                    return value["result"]

                async def job(operation, **request):
                    submitted = await call(operation, **request)
                    for _ in range(3600):
                        status = await call("job_status", job_id=submitted["job_id"])
                        if status["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
                            break
                        await asyncio.sleep(0.5)
                    assert status["status"] == "succeeded", status
                    artifact = await call(
                        "artifact_inspect", project_id=request["project_id"], ref=status["result"]
                    )
                    log.append(
                        dict(
                            operation=operation,
                            job_id=submitted["job_id"],
                            result=reference(artifact),
                            summary=artifact["summary"],
                            viewer_url=artifact.get("viewer_url"),
                        )
                    )
                    return artifact

                async def report_data(obj):
                    url = f"{args.url.rstrip('/')}/api/v1/projects/{pid}/artifacts/{obj['id']}/{obj['revision']}/files/report.json"
                    response = await http.get(url)
                    response.raise_for_status()
                    return response.json()

                prompt = await session.get_prompt("begin")
                assert prompt.messages
                log.append(dict(prompt="begin", status="RETURNED"))
                assessment = await call("folder_assess", source_id=source["id"], max_depth=6, max_files=200)
                (output / "folder_assessment.json").write_text(json.dumps(assessment, indent=2))
                entries = {f["path"]: f for f in assessment["files"]}
                assert "NORNE_ATW2013.DATA" in entries
                pid = (
                    await call(
                        "project_create",
                        name="Norne MCP publication demo — EQLNUM 1 and 3",
                        crs="LOCAL_METRIC",
                        vertical_datum="NORNE_SOURCE_DEPTH_DATUM_UNVERIFIED",
                    )
                )["id"]
                properties = await job(
                    "eclipse_import",
                    project_id=pid,
                    source_id=source["id"],
                    path="NORNE_ATW2013.DATA",
                    file_revision=entries["NORNE_ATW2013.DATA"]["file_revision"],
                    crs="LOCAL_METRIC",
                    vertical_datum="NORNE_SOURCE_DEPTH_DATUM_UNVERIFIED",
                    length_unit="m",
                    z_direction="down",
                    defaults={"SWAT": 0.25},
                    region_field="EQLNUM",
                    assumptions=ASSUMPTIONS,
                )
                await session.get_prompt(
                    "check_model",
                    arguments={
                        "context": "Check the complete imported Norne. Preserve all QC findings; do not change ACTNUM."
                    },
                )
                qc = await job(
                    "model_qc",
                    project_id=pid,
                    properties=reference(properties),
                    region_field="EQLNUM",
                    assumptions=ASSUMPTIONS,
                )
                qc_data = await report_data(qc)
                cases = [
                    dict(
                        region_id=r,
                        owc_z_m=-records[r]["owc_depth_m"],
                        goc_z_m=-records[r]["goc_depth_m"],
                        bo=1.2,
                        bg=0.005,
                        oil_gas_saturation=0.0,
                        gas_oil_saturation=0.05,
                    )
                    for r in (1, 3)
                ]
                base = dict(
                    project_id=pid,
                    properties=reference(properties),
                    region_field="EQLNUM",
                    scenarios=[dict(name="EQUIL-regions-1-and-3", regions=cases)],
                    parameters_confirmed=True,
                    assumptions=ASSUMPTIONS,
                )
                regional = await job("regional_volumes", **base)
                regional_data = await report_data(regional)
                assert regional_data["validation_status"] == "PASS"
                tornado = await job(
                    "sensitivity_tornado",
                    **base,
                    metric="STOIIP",
                    parameters=[
                        dict(region_id=r, field="phi", mode="multiplier", low=0.9, high=1.1) for r in (1, 3)
                    ],
                )
                tornado_data = await report_data(tornado)
                assert tornado_data["validation_status"] == "PASS"
                await call(
                    "scene_show", project_id=pid, ref=reference(properties), field="phi", stride=1, opacity=1
                )
                scene = await job("scene_export", project_id=pid, max_cells=200000)
                exported = await job(
                    "results_export",
                    project_id=pid,
                    reports=[reference(regional), reference(tornado), reference(qc)],
                    title="Norne public MCP demonstration — EQLNUM 1 and 3",
                    max_pdf_rows_per_table=30,
                    notes=ASSUMPTIONS,
                )
                for obj, wanted in [
                    (regional, ["report.json", "report.html"]),
                    (tornado, ["tornado.png"]),
                    (scene, ["scene.png", "scene.html", "scene.json"]),
                    (exported, ["results.xlsx", "results.pdf"]),
                ]:
                    for name in wanted:
                        response = await http.get(
                            f"{args.url.rstrip('/')}/api/v1/projects/{pid}/artifacts/{obj['id']}/{obj['revision']}/files/{name}"
                        )
                        response.raise_for_status()
                        (output / name).write_bytes(response.content)
                expected = dict(
                    status="PASS",
                    scope="Public demo; EQLNUM 1 and 3 only, not whole-field reserves",
                    source_commit="eaa2261683a97027e057c2bc49612ad1c86390b3",
                    active_model_cells=properties["summary"]["active_cells"],
                    selected_regions=[1, 3],
                    contacts=[records[r] for r in (1, 3)],
                    assumptions=ASSUMPTIONS,
                    qc_status=qc_data["status"],
                    qc_counts=qc_data["counts"],
                    regional=regional_data["tables"],
                    tornado=tornado_data["tables"]["tornado"],
                    independent_validation=regional_data["validation_status"],
                    project_id=pid,
                    scene=reference(scene),
                    export=reference(exported),
                    steps=log,
                    real_llm_client="NOT RUN",
                )
                (output / "expected.json").write_text(json.dumps(expected, indent=2))
                for path in output.glob("*.json"):
                    clean_json(path)
                print(
                    json.dumps(
                        dict(
                            status="PASS",
                            project_id=pid,
                            output=str(output),
                            volumes=regional_data["tables"]["scenarios"],
                        ),
                        indent=2,
                    )
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--home", default=".data")
    parser.add_argument("--norne-root", default="examples/reference/norne")
    parser.add_argument("--output", default="examples/reference/norne/results/mcp")
    parser.add_argument("--accept-demo-assumptions", action="store_true")
    asyncio.run(run(parser.parse_args()))
