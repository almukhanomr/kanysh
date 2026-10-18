"""Regression tests for the 2026-10-18 MCP smoke test findings (schemas, startup gate,
regional preflight, corner-point pinch-outs, GPU messages, QC, job logs, discovery, Z)."""

import asyncio
import json
import os
import sys
import time

import numpy as np
import pytest
import zarr
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from opensubsurface.adapters.folder_assess import inspect_text
from opensubsurface.adapters.large_grid import UNITS
from opensubsurface.adapters.local_sources import LocalSources
from opensubsurface.adapters.model_qc import geometry_flags
from opensubsurface.adapters.model_qc import run as model_qc
from opensubsurface.adapters.regional_volumes import evaluate
from opensubsurface.errors import DomainError
from opensubsurface.mcp.schema_docs import undocumented, unresolved_refs
from opensubsurface.mcp.server import create_mcp

CUBE = np.array(
    [[0, 0, 0], [10, 0, 0], [0, 10, 0], [10, 10, 0], [0, 0, -10], [10, 0, -10], [0, 10, -10], [10, 10, -10]],
    float,
)


def cornerpoint(tmp_path, cells, missing=(), name="grid"):
    """Small cornerpoint-zarr-v1 artifact; corners 0..3 top, 4..7 bottom (ECLIPSE storage)."""
    n = len(cells)
    arrays = dict(
        corners=np.asarray(cells, float),
        active=np.ones(n, bool),
        zones=np.ones(n, np.int32),
        phi=np.full(n, 0.2),
        ntg=np.full(n, 0.8),
        sw=np.full(n, np.nan if "SWAT" in missing else 0.25),
        permeability_md=np.full(n, 100.0),
        kz_ratio=np.full(n, 0.1),
    )
    arrays["FIPNUM"] = arrays["zones"].copy()
    path = tmp_path / (name + ".zip")
    with zarr.ZipStore(str(path), mode="w") as store:
        group = zarr.group(store=store)
        group.attrs.update(storage="cornerpoint-zarr-v1", shape=[n, 1, 1], order="ECLIPSE")
        for key, value in arrays.items():
            group.create_dataset(key, data=value, chunks=(n, 8, 3) if key == "corners" else (n,))
    return dict(
        id="properties-test",
        revision=1,
        content_hash="0" * 64,
        summary=dict(
            storage="cornerpoint-zarr-v1",
            grid=dict(shape=[n, 1, 1], extent=[0, 10 * n, 0, 10, -10, 0]),
            crs="LOCAL_METRIC",
            vertical_datum="TEST",
            block_cells=n,
            active_cells=n,
            zone_ids=[1],
            units=UNITS,
            order="ECLIPSE",
            missing_properties=list(missing),
        ),
        paths={"grid.zip": str(path)},
    )


def pinched_cube(dx=0):
    cell = CUBE + [dx, 0, 0]
    cell[7] = cell[3]  # pillar 3 collapsed: zero-thickness corner (pinch-out)
    return cell


def twisted_cube(dx=0):
    cell = CUBE + [dx, 0, 0]
    cell[[0, 1]] = cell[[1, 0]]
    return cell


def regional(policy="strict", **case):
    region = dict(region_id=1, owc_z_m=-20.0, bo=1.0, sg_in_oil_zone=0.0, **case)
    return dict(
        region_field="FIPNUM",
        scenarios=[dict(name="base", regions=[region])],
        parameters_confirmed=True,
        assumptions=["synthetic"],
        geometry_policy=policy,
    )


# 1. Self-contained, documented MCP schemas -------------------------------------------------


class _NoService:
    pass


@pytest.mark.parametrize("profile", ["agent", "full"])
def test_every_tool_schema_is_resolved_and_documented(profile):
    tools = asyncio.run(create_mcp(_NoService(), profile=profile).list_tools())
    assert tools
    for tool in tools:
        assert "$defs" not in json.dumps(tool.inputSchema), tool.name
        assert unresolved_refs(tool.inputSchema) == [], tool.name
        assert undocumented(tool.inputSchema) == [], (tool.name, undocumented(tool.inputSchema))


def test_schema_enums_examples_units_and_aliases():
    tools = {t.name: t for t in asyncio.run(create_mcp(_NoService(), profile="agent").list_tools())}
    request = tools["regional_volumes"].inputSchema["properties"]["request"]
    policy = request["properties"]["execution"]["properties"]["device_policy"]
    assert all(value in policy["description"] for value in ("cpu", "prefer_gpu", "require_gpu"))
    scenarios = request["properties"]["scenarios"]
    assert scenarios["examples"][0][0]["regions"][0]["owc_z_m"] == -2692.0
    region = scenarios["items"]["properties"]["regions"]["items"]
    assert "-2692" in region["properties"]["owc_z_m"]["description"]
    assert region["properties"]["oil_gas_saturation"]["deprecated"] is True
    assert "sg_in_oil_zone" not in region.get("required", [])
    assert "exclude_flagged" in request["properties"]["geometry_policy"]["description"]
    plan = tools["calculation_plan"].inputSchema["properties"]["request"]["properties"]
    assert plan["contacts"]["examples"] and plan["zones"]["examples"] and plan["inputs"]["examples"]
    assert (
        "diagnostics" in tools
        and tools["job_status"].inputSchema["properties"]["request"]["properties"]["verbose"]["description"]
    )


def test_validation_errors_name_json_paths_and_aliases(service):
    async def scenario():
        server = create_mcp(service, profile="agent")
        async with create_connected_server_and_client_session(server._mcp_server) as client:

            async def call(name, request):
                reply = await client.call_tool(name, arguments=dict(request=request))
                return json.loads(reply.content[0].text)

            base = dict(project_id="project-x", properties=dict(id="p", revision=1), **regional())
            bad = json.loads(json.dumps(base))
            bad["scenarios"][0]["regions"][0].update(goc_z_m=-30.0, bg=0.005, so_in_gas_zone=0.05)
            error = (await call("regional_volumes", bad))["error"]
            assert error["code"] == "INVALID_ARGUMENTS"
            assert error["field"] == "scenarios[0].regions[0].goc_z_m"
            assert "positive upward" in error["message"] and error["remediation"]
            bad["scenarios"][0]["regions"][0].update(goc_z_m=-10.0, bg=None)
            error = (await call("regional_volumes", bad))["error"]
            assert error["field"] == "scenarios[0].regions[0].bg"
            both = json.loads(json.dumps(base))
            both["scenarios"][0]["regions"][0]["oil_gas_saturation"] = 0.0
            error = (await call("regional_volumes", both))["error"]
            assert error["field"] == "scenarios[0].regions[0].oil_gas_saturation"
            old = json.loads(json.dumps(base))
            old["scenarios"][0]["regions"][0]["oil_gas_saturation"] = old["scenarios"][0]["regions"][0].pop(
                "sg_in_oil_zone"
            )
            error = (await call("regional_volumes", old))["error"]
            assert error["code"] == "NOT_FOUND", error  # alias accepted; fails later on the unknown project

    asyncio.run(scenario())


# 2. Startup gate ------------------------------------------------------------------------------


def test_gate_allows_discovery_after_service_ready(tmp_path):
    from opensubsurface.desktop import DesktopRuntime, StartupError
    from opensubsurface.service import Service

    runtime = DesktopRuntime(tmp_path / "home")
    with pytest.raises(StartupError) as raised:
        runtime.require_ready("source_list")
    assert raised.value.as_dict()["waiting_for"]
    runtime.service = Service(tmp_path / "home")
    try:
        runtime.enter("viewer_start")
        runtime.status("SERVICE_READY")
        runtime.service_ready.set()
        assert runtime.require_ready("source_list") is runtime.service
        assert runtime.require_ready("folder_assess") is runtime.service
        with pytest.raises(StartupError) as raised:
            runtime.require_ready("regional_volumes")
        error = raised.value.as_dict()
        assert error["code"] == "STARTING" and error["stage"] == "SERVICE_READY"
        assert error["substage"] == "viewer_start" and "viewer" in error["waiting_for"]
        assert error["elapsed_s"] >= 0 and error["remediation"]
        from opensubsurface.diagnostics import diagnostics

        report = diagnostics(runtime, dict(lines=20))
        assert report["startup"]["substage"] == "viewer_start"
        assert any("SERVICE_READY" in line for line in report["startup_log_tail"])
        assert "OPENSUBSURFACE_TOKEN" not in json.dumps(report)
    finally:
        runtime.service.close()


@pytest.mark.asyncio
async def test_cold_start_source_list_within_five_seconds_of_service_ready(tmp_path):
    entry = tmp_path / "server.py"
    entry.write_text(
        "import time\nimport opensubsurface.setup as setup\n"
        "setup.ensure_viewer = lambda *a, **k: (time.sleep(40), {'status': 'FAILED'})[1]\n"
        "from opensubsurface.desktop import run\nrun()\n"
    )
    home = tmp_path / "home"
    folder = tmp_path / "data"
    folder.mkdir()
    env = dict(os.environ, OPENSUBSURFACE_HOME=str(home), KANYSH_OPEN_BROWSER="0", KANYSH_VARIANT="cpu")
    env["KANYSH_SOURCE_FOLDER"] = str(folder)
    with (tmp_path / "client.log").open("w") as errlog:
        async with stdio_client(
            StdioServerParameters(command=sys.executable, args=[str(entry)], env=env), errlog=errlog
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                ready_at, answered_at, starting = None, None, []
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline and answered_at is None:
                    try:
                        status = json.loads((home / "startup-status.json").read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        status = {}
                    if ready_at is None and status.get("stage") == "SERVICE_READY":
                        ready_at = time.monotonic()
                    reply = json.loads(
                        (await session.call_tool("source_list", arguments=dict(request={}))).content[0].text
                    )
                    if "result" in reply:
                        answered_at = time.monotonic()
                        assert len(reply["result"]) == 1
                    else:
                        assert reply["error"]["code"] == "STARTING" and reply["error"]["waiting_for"]
                        starting.append(reply["error"])
                    await asyncio.sleep(0.1)
                assert answered_at is not None, starting[-1:]
                assert answered_at - (ready_at or answered_at) <= 5
                heavy = json.loads(
                    (await session.call_tool("compute_targets_list", arguments=dict(request={})))
                    .content[0]
                    .text
                )
                assert heavy["error"]["code"] == "STARTING"
                assert heavy["error"]["substage"] == "viewer_start" and heavy["error"]["waiting_for"]
                diag = json.loads(
                    (await session.call_tool("diagnostics", arguments=dict(request={}))).content[0].text
                )["result"]
                assert diag["startup"]["stage"] == "SERVICE_READY" and diag["startup_log_tail"]


# 3./4./10. Regional preflight, geometry policy and Z convention --------------------------------


def _deck(folder, swat=True):
    pillars = [v for j in range(2) for i in range(3) for v in [i * 10, j * 10, 1000, i * 10, j * 10, 1020]]
    folder.mkdir(exist_ok=True)
    (folder / "model.DATA").write_text(
        "RUNSPEC\nDIMENS\n2 1 2 /\nMETRIC\nGRID\nCOORD\n"
        + " ".join(map(str, pillars))
        + " /\nZCORN\n8*1000 16*1010 8*1020 /\nACTNUM\n4*1 /\nPORO\n4*0.2 /\nNTG\n4*0.8 /\nPERMX\n4*100 /\nPERMZ\n4*10 /\n"
        + ("PROPS\nSWAT\n4*0.25 /\n" if swat else "")
        + "REGIONS\nFIPNUM\n2*1 2*2 /\nEQLNUM\n4*1 /\nEND\n"
    )


def _import(service, tmp_path, swat):
    folder = tmp_path / ("deck-swat" if swat else "deck-noswat")
    _deck(folder, swat)
    source = LocalSources(service.store).register(folder.name, folder)
    assessed = service.invoke("folder_assess", dict(source_id=source["id"]))
    listing = {f["path"]: f for f in assessed["files"]}
    pid = service.invoke("project_create", dict(name="t", crs="LOCAL_METRIC", vertical_datum="TEST"))["id"]
    props = service.wait(
        service.invoke(
            "eclipse_import",
            dict(
                project_id=pid,
                source_id=source["id"],
                path="model.DATA",
                file_revision=listing["model.DATA"]["file_revision"],
                crs="LOCAL_METRIC",
                vertical_datum="TEST",
                length_unit="m",
                z_direction="down",
                assumptions=["synthetic"],
            ),
        )
    )
    return pid, props


def test_regional_preflight_refuses_synchronously_with_field_paths(service, tmp_path):
    pid, props = _import(service, tmp_path, swat=False)
    summary = props["summary"]
    assert summary["input_z_direction"] == "down" and summary["stored_z_direction"] == "up"
    assert summary["z_conversion"] == "z_stored = -depth"
    assert summary["region_ids"]["FIPNUM"] == [1, 2] and summary["region_ids"]["EQLNUM"] == [1]
    assert summary["grid"]["extent"][4:] == [-1020.0, -1000.0]
    jobs_before = len(service.store.list_jobs(pid))
    request = dict(project_id=pid, properties=dict(id=props["id"], revision=props["revision"]), **regional())
    request["scenarios"][0]["regions"].append(dict(region_id=2, owc_z_m=-1015.0, bo=1.0, sg_in_oil_zone=0.0))
    request["scenarios"][0]["regions"][0]["owc_z_m"] = -1015.0
    with pytest.raises(DomainError) as raised:
        service.invoke("regional_volumes", request)
    error = raised.value.as_dict()
    assert error["code"] == "MISSING_PROPERTY"
    assert error["field"] == "scenarios[*].regions[*].sw_override"
    assert "SWAT" in error["message"] and "sw_override" in error["remediation"]
    assert error["details"]["fields"] == [
        "scenarios[0].regions[0].sw_override",
        "scenarios[0].regions[1].sw_override",
    ]
    request["scenarios"][0]["regions"][0]["region_id"] = 7
    with pytest.raises(DomainError) as raised:
        service.invoke("regional_volumes", request)
    assert raised.value.code == "UNKNOWN_REGION" and raised.value.field == "scenarios[0].regions[0].region_id"
    request["scenarios"][0]["regions"][0].update(region_id=1, owc_z_m=1015.0)
    with pytest.raises(DomainError) as raised:
        service.invoke("regional_volumes", request)
    assert raised.value.code == "CONTACT_SIGN" and raised.value.field == "scenarios[0].regions[0].owc_z_m"
    assert len(service.store.list_jobs(pid)) == jobs_before  # nothing was queued
    for case in request["scenarios"][0]["regions"]:
        case.update(owc_z_m=-1015.0, sw_override=0.25)
    report = service.wait(service.invoke("regional_volumes", request))
    assert report["summary"]["validation_status"] == "PASS"


def test_pinched_pillar_is_valid_twisted_cell_needs_explicit_policy(tmp_path):
    flags = geometry_flags(np.array([pinched_cube(), twisted_cube(10)]), "cornerpoint-zarr-v1")
    assert flags["valid"].tolist() == [True, False]
    assert flags["pinched"].tolist() == [True, False] and flags["collapsed_pillars"][0] == 1
    assert flags["twisted"].tolist() == [False, True] and not flags["degenerate"].any()
    obj = cornerpoint(tmp_path, [pinched_cube(), twisted_cube(10)])
    out = tmp_path / "qc"
    out.mkdir()
    qc = model_qc(
        obj, dict(region_field="FIPNUM", small_cluster_cells=1, max_examples=10, assumptions=[]), out
    )
    assert qc["counts"]["pinched_pillar_cell"] == 1 and qc["counts"]["degenerate_cell"] == 0
    assert qc["counts"]["twisted_cell"] == 1 and qc["status"] == "ISSUES"
    with pytest.raises(DomainError) as raised:
        evaluate(obj, regional("strict"))
    error = raised.value.as_dict()
    assert error["code"] == "INVALID_GEOMETRY" and error["field"] == "geometry_policy"
    assert "model_qc" in error["remediation"] and "exclude_flagged" in error["remediation"]
    result = evaluate(obj, regional("exclude_flagged"))
    assert result["status"] == result["validation_status"] == "PASS_WITH_EXCLUSIONS"
    (exclusion,) = result["tables"]["geometry_exclusions"]
    assert exclusion["excluded_cells"] == 1 and exclusion["included_cells"] == 1
    assert exclusion["excluded_GRV_bbox_m3"] == pytest.approx(1000)
    assert exclusion["excluded_PV_bbox_m3"] == pytest.approx(1000 * 0.2 * 0.8)
    assert 0 < exclusion["share_of_region_GRV_tetra6"] < 1
    assert result["tables"]["excluded_cell_witnesses"][0]["code"] == "twisted_cell"
    pinched_only = evaluate(cornerpoint(tmp_path, [pinched_cube()], name="pinched"), regional("strict"))
    assert pinched_only["validation_status"] == "PASS"
    assert 0 < pinched_only["tables"]["regions"][0]["GRV"] < 1000


# 7. model_qc missing property ------------------------------------------------------------------


def test_missing_property_is_not_a_range_violation(tmp_path):
    obj = cornerpoint(tmp_path, [CUBE, CUBE + [10, 0, 0]], missing=("SWAT",))
    out = tmp_path / "qc"
    out.mkdir()
    qc = model_qc(
        obj, dict(region_field="FIPNUM", small_cluster_cells=1, max_examples=10, assumptions=[]), out
    )
    assert "property_range:sw" not in qc["counts"] and qc["status"] == "PASS"
    assert qc["missing_properties"][0]["code"] == "missing_property:sw"
    assert qc["missing_properties"][0]["severity"] == "WARNING"
    assert "missing_property:sw" in (out / "issues.csv").read_text()


# 6. GPU coverage messages ---------------------------------------------------------------------


def test_device_matrix_and_gpu_refusal_messages(service, tmp_path):
    targets = service.invoke("compute_targets_list", {})[0]
    matrix = targets["device_matrix"]
    assert matrix["model_build"]["devices"] == ["cpu", "cuda"] and matrix["regional_volumes"]["devices"] == [
        "cpu"
    ]
    pid, props = _import(service, tmp_path, swat=True)
    with pytest.raises(DomainError) as raised:
        service.invoke(
            "calculation_plan",
            dict(
                project_id=pid,
                properties=dict(id=props["id"], revision=props["revision"]),
                zone_ids=[1],
                bo=1.2,
                contacts=[dict(name="c", z_m=-1010)],
                assumptions=["synthetic"],
                execution=dict(device_policy="require_gpu"),
            ),
        )
    error = raised.value.as_dict()
    assert error["code"] == "NO_COMPATIBLE_GPU" and error["field"] == "execution.device_policy"
    assert "model_build" in error["message"] and "prefer_gpu" in error["remediation"]


# 8. Compact job status, logs and run progress -------------------------------------------------


def test_compact_job_status_logs_and_calculation_progress(service, tmp_path):
    pid, props = _import(service, tmp_path, swat=True)
    plan = service.invoke(
        "calculation_plan",
        dict(
            project_id=pid,
            properties=dict(id=props["id"], revision=props["revision"]),
            zone_ids=[1, 2],
            bo=1.2,
            contacts=[dict(name="c", z_m=-1010)],
            assumptions=["synthetic"],
        ),
    )
    run = service.invoke(
        "calculation_run", dict(project_id=pid, plan=dict(id=plan["id"], revision=plan["revision"]))
    )
    for _ in range(1200):
        status = service.invoke("calculation_status", dict(project_id=pid, run_id=run["run_id"]))
        if status["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
            break
        assert status["progress"] is None or 0 <= status["progress"] <= 1
        time.sleep(0.1)
    assert status["status"] == "succeeded", status
    assert status["progress"] == 1.0 and status["nodes"]["report"]["status"] == "succeeded"
    compact = service.invoke("job_status", dict(job_id=run["run_id"]))
    assert {"id", "status", "stage", "progress", "error", "result", "payload_hash"} <= compact.keys()
    assert "payload" not in compact and "events" not in compact
    assert len(json.dumps(compact)) < len(
        json.dumps(service.invoke("job_status", dict(job_id=run["run_id"], verbose=True)))
    )
    logs = service.invoke("job_logs", dict(job_id=run["run_id"]))
    assert "node report" in logs["logs"]["workflow"] and logs["logs"]["stages"]
    assert logs["child_jobs"] and all(
        "worker started" in (c["worker_tail"] or "")
        for c in logs["child_jobs"]
        if c["operation"] != "properties_reference"
    )


# 9. folder_assess proposals ------------------------------------------------------------------


def test_folder_assess_proposes_every_equil_region_rsvd_and_pvt_tables():
    text = (
        "EQUIL\n-- Datum P woc Pc goc Pc\n"
        "2582.0 268.56 2692.0 0.0 2582.0 0.0 1 0 0 / C+D\n"
        "2500.0 263.41 2585.5 0.0 2500.0 0.0 2 0 0 / G\n\n"
        "RSVD\n2582.0 120.25\n2697.0 106.77 /\n2500 94.5\n2590.0 94.1 /\n\n"
        "PVTO\n20.59 50.00 1.10615 1.180\n 75.00 1.10164 1.247 /\n28.19 70.0 1.12 1.06 /\n/\n"
        "30 50 1.1 1.0 /\n/\n"
    )
    _, _, proposals = inspect_text("E3.prop", text.encode())
    equil = [p for p in proposals if p["parameter"] == "EQUIL"]
    assert [p["region"] for p in equil] == [1, 2] and [p["lines"] for p in equil] == [[3, 3], [4, 4]]
    assert equil[1]["values"]["owc_depth"] == 2585.5
    assert equil[0]["regional_volumes_candidate"]["owc_z_m"] == -2692.0
    assert equil[0]["regional_volumes_candidate"]["goc_z_m"] == -2582.0
    rsvd = [p for p in proposals if p["parameter"] == "RSVD"]
    assert [(p["region"], p["lines"]) for p in rsvd] == [(1, [7, 8]), (2, [9, 10])]
    pvto = [p for p in proposals if p["parameter"] == "PVTO"]
    assert [(p["region"], p["lines"], p["records"]) for p in pvto] == [(1, [13, 15], 2), (2, [17, 17], 1)]
    assert all(p["status"] == "PROPOSAL_REQUIRES_USER_CONFIRMATION" for p in proposals)
    assert all("bo" not in json.dumps(p.get("values", {})).lower() for p in pvto)
