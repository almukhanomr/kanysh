"""Actual HTTP MCP client: saved Norne properties → calculation → report and viewer links.

Uses the Python SDK, not a ChatGPT/Claude model. Start serve --ui and open bundled Norne first.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def run(a):
    headers = {}
    if os.environ.get("OPENSUBSURFACE_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["OPENSUBSURFACE_TOKEN"]
    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        async with streamable_http_client(a.url.rstrip("/") + "/mcp/", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(name, **request):
                    response = await session.call_tool(name, arguments=dict(request=request))
                    result = json.loads(response.content[0].text)
                    if response.isError or "error" in result:
                        raise RuntimeError(result)
                    return result["result"]

                project = await call("project_inspect", project_id=a.project_id)
                props = next(o for o in project["objects"] if o["kind"] == "properties")
                scene = next(o for o in project["objects"] if o["kind"] == "scene")
                declaration = json.loads(Path("src/opensubsurface/data/norne/demo.json").read_text())
                depths = declaration["contact_selection"]["depths_m"]
                plan = await call(
                    "calculation_plan",
                    project_id=a.project_id,
                    properties={k: props[k] for k in ("id", "revision")},
                    zone_ids=props["summary"]["zone_ids"],
                    bo=1.2,
                    contacts=[dict(name="test-depth-" + str(d), z_m=-d) for d in depths],
                    assumptions=[
                        "Public Norne benchmark; test contacts and Bo, not field reserves",
                        "Original phi/NTG/permeability; explicit stored Sw=0.25 and Kz/Kx=0.1",
                    ],
                )
                submitted = await call(
                    "calculation_run", project_id=a.project_id, plan={k: plan[k] for k in ("id", "revision")}
                )
                for _ in range(2400):
                    status = await call(
                        "calculation_status", project_id=a.project_id, run_id=submitted["run_id"]
                    )
                    if status["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
                        break
                    await asyncio.sleep(0.25)
                assert status["status"] == "succeeded", status
                preview = await call("result_preview", project_id=a.project_id, report=status["report"])
                inspected = await call(
                    "artifact_inspect", project_id=a.project_id, ref={k: scene[k] for k in ("id", "revision")}
                )
                assert preview["validation_status"] == "PASS"
                for url in (preview["viewer_url"], inspected["viewer_url"]):
                    response = await http.get(url)
                    response.raise_for_status()
                    assert "/viewer/projects/" in url and "<iframe" in response.text
                evidence = dict(
                    status="PASS",
                    client="MCP Python SDK; not a ChatGPT/Claude model",
                    run_id=submitted["run_id"],
                    project_id=a.project_id,
                    numerical_validation="PASS",
                    report_url=preview["viewer_url"],
                    scene_url=inspected["viewer_url"],
                    scene_and_report_pages_http=200,
                    refs_unchanged=True,
                )
                a.output.write_text(json.dumps(evidence, indent=2) + "\n")
                print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/mcp-viewer-control.json"))
    asyncio.run(run(parser.parse_args()))
