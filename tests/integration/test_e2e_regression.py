"""End-to-end agent regression through the real stdio Desktop extension (MCP client).

Repeats the 2026-10-18 smoke-test path: start -> source_list -> folder_assess -> project_create ->
eclipse_import (Norne) -> model_qc -> regional_volumes -> calculation_plan/plan_validate/
calculation_run (GemPy, require_gpu) -> report_export. Norne values are smoke-test assumptions,
not geology. The Norne deck is not shipped: set KANYSH_NORNE_DIR to the folder holding
NORNE_ATW2013.DATA and INCLUDE/ (or fetch it with scripts/fetch_norne_deck.py).
Per-step wall times are written to e2e-timings.json in the test directory and printed.
"""

import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from opensubsurface.calculations.validation import ATOL, RTOL

REPO = Path(__file__).resolve().parents[2]
NORNE = Path(os.environ.get("KANYSH_NORNE_DIR") or REPO / "examples/reference/norne/full/norne")
TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")
# EQLNUM, OWC depth m, GOC depth m, Bo, Bg, Sw, So in gas cap (smoke-test assumptions).
NORNE_CASES = [
    (1, 2692.0, 2582.0, 1.33),
    (2, 2585.5, 2500.0, 1.30),
    (3, 2618.0, 2582.0, 1.33),
    (4, 2400.0, 2200.0, 1.30),
    (5, 2693.3, 2585.0, 1.33),
]


def cuda_available():
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


class Agent:
    """Minimal MCP agent: retries only STARTING, records wall time per named step."""

    def __init__(self, session):
        self.session, self.timings = session, {}

    async def raw(self, tool, /, **request):
        reply = await self.session.call_tool(tool, arguments=dict(request=request))
        assert not reply.isError, reply.content
        return json.loads(reply.content[0].text)

    async def call(self, tool, /, **request):
        for _ in range(900):
            value = await self.raw(tool, **request)
            if value.get("error", {}).get("code") != "STARTING":
                assert "error" not in value, value
                return value["result"]
            assert value["error"]["waiting_for"]
            await asyncio.sleep(0.2)
        pytest.fail("Desktop did not become ready")

    async def wait(self, job_id, seconds=900):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            record = await self.call("job_status", job_id=job_id)
            assert "payload" not in record  # compact by default
            if record["status"] in TERMINAL:
                return record
            await asyncio.sleep(0.25)
        pytest.fail("job timeout " + job_id)

    @asynccontextmanager
    async def step(self, name):
        started = time.monotonic()
        yield
        self.timings[name] = round(time.monotonic() - started, 2)


@asynccontextmanager
async def desktop(tmp_path, sources):
    from opensubsurface.adapters.local_sources import LocalSources
    from opensubsurface.persistence.store import Store

    home = tmp_path / "home"
    store = Store(home)
    try:
        for name, folder in sources:
            LocalSources(store).register(name, folder)
    finally:
        store.engine.dispose()
    env = dict(
        os.environ,
        OPENSUBSURFACE_HOME=str(home),
        KANYSH_OPEN_BROWSER="0",
        KANYSH_VARIANT="gpu" if cuda_available() else "cpu",
    )
    with (tmp_path / "client.log").open("w", encoding="utf-8") as errlog:
        async with stdio_client(
            StdioServerParameters(command=sys.executable, args=["-m", "opensubsurface.desktop"], env=env),
            errlog=errlog,
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield Agent(session)


def report(tmp_path, agent, record_property, name):
    path = tmp_path / "e2e-timings.json"
    path.write_text(json.dumps(agent.timings, indent=2), encoding="utf-8")
    record_property(name, json.dumps(agent.timings))
    print("\n" + name + " step seconds: " + json.dumps(agent.timings))


@pytest.mark.skipif(
    not (NORNE / "NORNE_ATW2013.DATA").is_file(), reason="Set KANYSH_NORNE_DIR to the Norne deck"
)
@pytest.mark.asyncio
async def test_norne_agent_regression(tmp_path, record_property):
    async with desktop(tmp_path, [("Norne", NORNE)]) as agent:
        async with agent.step("start"):
            assert (await agent.call("start"))["compute_started"] is False
        async with agent.step("source_list"):
            (source,) = await agent.call("source_list")
        async with agent.step("folder_assess"):
            assessment = await agent.call("folder_assess", source_id=source["id"])
        equil = {p["region"]: p for p in assessment["proposals"] if p["parameter"] == "EQUIL"}
        assert sorted(equil) == [1, 2, 3, 4, 5]
        assert [equil[r]["values"]["owc_depth"] for r in range(1, 6)] == [c[1] for c in NORNE_CASES]
        assert any(p["parameter"] == "RSVD" for p in assessment["proposals"])
        deck = next(f for f in assessment["files"] if f["path"].endswith("NORNE_ATW2013.DATA"))
        async with agent.step("project_create"):
            pid = (
                await agent.call(
                    "project_create", name="Norne regression", crs="EPSG:23032", vertical_datum="MSL"
                )
            )["id"]
        async with agent.step("eclipse_import"):
            submitted = await agent.call(
                "eclipse_import",
                project_id=pid,
                source_id=source["id"],
                path=deck["path"],
                file_revision=deck["file_revision"],
                crs="EPSG:23032",
                vertical_datum="MSL",
                length_unit="m",
                z_direction="down",
                region_field="EQLNUM",
                assumptions=["Smoke-test regression; CRS/datum confirmed for the test, not geology"],
            )
            imported = await agent.wait(submitted["job_id"])
        assert imported["status"] == "succeeded", imported
        properties = imported["result"]
        props = await agent.call("artifact_inspect", project_id=pid, ref=properties)
        assert props["summary"]["z_conversion"] == "z_stored = -depth"
        assert props["summary"]["region_ids"]["EQLNUM"] == [1, 2, 3, 4, 5]
        assert "SWAT" in props["summary"]["missing_properties"]
        async with agent.step("model_qc"):
            submitted = await agent.call(
                "model_qc", project_id=pid, properties=properties, region_field="EQLNUM"
            )
            qc_job = await agent.wait(submitted["job_id"])
        qc = (await agent.call("artifact_inspect", project_id=pid, ref=qc_job["result"]))["summary"]["counts"]
        assert qc["degenerate_cell"] == 0 and qc["twisted_cell"] == 1 and qc["pinched_pillar_cell"] == 243
        assert "property_range:sw" not in qc

        def cases(sw=True):
            rows = []
            for region, owc, goc, bo in NORNE_CASES:
                row = dict(
                    region_id=region,
                    owc_z_m=-owc,
                    goc_z_m=-goc,
                    bo=bo,
                    bg=0.004737,
                    sg_in_oil_zone=0.0,
                    so_in_gas_zone=0.05,
                )
                if sw:
                    row["sw_override"] = 0.20
                rows.append(row)
            return rows

        base = dict(
            project_id=pid,
            properties=properties,
            region_field="EQLNUM",
            parameters_confirmed=True,
            assumptions=["Smoke-test Bo/Bg/Sw/So per EQLNUM; contacts from EQUIL depths (Z up)"],
        )
        async with agent.step("regional_volumes_preflight_refusal"):
            refusal = await agent.raw(
                "regional_volumes", **base, scenarios=[dict(name="no-sw", regions=cases(sw=False))]
            )
        assert refusal["error"]["code"] == "MISSING_PROPERTY"
        assert refusal["error"]["field"] == "scenarios[*].regions[*].sw_override"
        async with agent.step("regional_volumes_strict"):
            strict = await agent.call(
                "regional_volumes", **base, scenarios=[dict(name="base", regions=cases())]
            )
            strict = await agent.wait(strict["job_id"])
        assert strict["status"] == "failed" and strict["error"]["code"] == "INVALID_GEOMETRY"
        assert "geometry_policy" in strict["error"]["remediation"]
        assert qc_job["result"]["id"] in strict["error"]["remediation"]
        async with agent.step("regional_volumes_exclude_flagged"):
            submitted = await agent.call(
                "regional_volumes",
                **base,
                geometry_policy="exclude_flagged",
                scenarios=[dict(name="base", regions=cases())],
            )
            regional = await agent.wait(submitted["job_id"])
        assert regional["status"] == "succeeded", regional
        summary = (await agent.call("artifact_inspect", project_id=pid, ref=regional["result"]))["summary"]
        assert summary["validation_status"] == "PASS_WITH_EXCLUSIONS"
        preview = await agent.call("result_preview", project_id=pid, report=regional["result"])
        assert preview["validation_status"] == "PASS_WITH_EXCLUSIONS"
        logs = await agent.call("job_logs", job_id=submitted["job_id"])
        assert "worker finished: ok" in logs["logs"]["worker"]
        diagnostics = await agent.call("diagnostics")
        assert diagnostics["startup"]["stage"] == "MCP_READY"
    report(tmp_path, agent, record_property, "norne")


@pytest.mark.gpu
@pytest.mark.skipif(not cuda_available(), reason="NVIDIA CUDA unavailable")
@pytest.mark.asyncio
async def test_gempy_gpu_control_regression(tmp_path, record_property):
    folder = tmp_path / "Synthetic-layers"
    folder.mkdir()
    for name in ("surfaces.csv", "orientations.csv"):
        (folder / name).write_bytes((REPO / "examples/agent-demo" / name).read_bytes())
    async with desktop(tmp_path, [("Synthetic-layers", folder)]) as agent:
        (source,) = await agent.call("source_list")
        files = {f["path"]: f for f in (await agent.call("folder_assess", source_id=source["id"]))["files"]}
        pid = (
            await agent.call(
                "project_create",
                name="Synthetic GemPy GPU control",
                crs="LOCAL_METRIC",
                vertical_datum="SYNTHETIC_MSL",
            )
        )["id"]
        targets = await agent.call("compute_targets_list")
        assert "model_build" in targets[0]["gpu_capable_operations"]
        inputs = [
            dict(
                kind=kind,
                source_id=source["id"],
                path=kind + ".csv",
                file_revision=files[kind + ".csv"]["file_revision"],
                units=dict(x="m", y="m", z="m"),
            )
            for kind in ("surfaces", "orientations")
        ]
        async with agent.step("calculation_plan"):
            plan = await agent.call(
                "calculation_plan",
                project_id=pid,
                name="Synthetic GemPy GPU control",
                method="gempy",
                horizontal_assumption=False,
                inputs=inputs,
                grid=dict(shape=[50, 50, 40], extent=[0, 1000, 0, 1000, -1040, -1000]),
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
                assumptions=["Synthetic analytical control; no field data"],
                execution=dict(device_policy="require_gpu"),
            )
        plan_ref = dict(id=plan["id"], revision=plan["revision"])
        async with agent.step("plan_validate"):
            assert (await agent.call("plan_validate", project_id=pid, plan=plan_ref))["status"] == "VALID"
        async with agent.step("calculation_run"):
            run = await agent.call("calculation_run", project_id=pid, plan=plan_ref)
            for _ in range(2400):
                status = await agent.call("calculation_status", project_id=pid, run_id=run["run_id"])
                if status["status"] in TERMINAL:
                    break
                assert status["progress"] is None or 0 <= status["progress"] <= 1
                await asyncio.sleep(0.25)
        assert status["status"] == "succeeded", status
        assert agent.timings["calculation_run"] < 60, agent.timings
        async with agent.step("report_export"):
            exported = await agent.wait(
                (await agent.call("report_export", project_id=pid, run_id=run["run_id"]))["job_id"]
            )
        assert exported["status"] == "succeeded", exported
        report_obj = await agent.call("artifact_inspect", project_id=pid, ref=status["report"])
        assert report_obj["summary"]["validation_status"] == "PASS"
        preview = await agent.call("result_preview", project_id=pid, report=status["report"])
        assert preview["validation_status"] == "PASS"
        logs = await agent.call("job_logs", job_id=run["run_id"])
        assert "workflow succeeded" in logs["logs"]["workflow"]
        model = next(c for c in logs["child_jobs"] if c["operation"] == "model_build")
        assert (await agent.call("job_status", job_id=model["job_id"], verbose=True))["backend"] == "cuda"
    data = json.loads(
        (tmp_path / "home" / "blobs" / report_obj["files"]["report.json"]).read_text(encoding="utf-8")
    )
    assert [row["STOIIP"] for row in data["contacts"]] == pytest.approx([2e6, 1e6, 0], rel=RTOL, abs=ATOL)
    report(tmp_path, agent, record_property, "gempy_gpu")
