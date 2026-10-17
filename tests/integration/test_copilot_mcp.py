"""Real MCP + isolated worker path; analytic grid and explicit synthetic assumptions."""

import asyncio
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from opensubsurface.adapters.local_sources import LocalSources
from opensubsurface.api.app import create_app


@pytest.mark.asyncio
async def test_mcp_import_qc_region_diff_reconcile_uncertainty_and_exports(service, tmp_path):
    folder = tmp_path / "exchange"
    folder.mkdir()
    pillars = [v for j in range(2) for i in range(3) for v in [i * 10, j * 10, 0, i * 10, j * 10, 20]]
    (folder / "model.DATA").write_text(
        "RUNSPEC\nDIMENS\n2 1 2 /\nMETRIC\nGRID\nCOORD\n"
        + " ".join(map(str, pillars))
        + " /\nZCORN\n8*0 16*10 8*20 /\nACTNUM\n4*1 /\nPORO\n4*0.2 /\nNTG\n4*0.8 /\nPERMX\n4*100 /\nPROPS\nSWAT\n4*0.25 /\nREGIONS\nFIPNUM\n2*1 2*2 /\nEND\n"
    )
    (folder / "volumes.csv").write_text("region_id,metric,value,unit\n1,STOIIP,200,sm3\n2,STOIIP,200,sm3\n")
    (folder / "survey.csv").write_text("well_id,md,x,y,z\nA,0,5,5,0\nA,20,5,5,-20\n")
    (folder / "well.las").write_text(
        "~Version\nVERS. 2.0\nWRAP. NO\n~Well\nSTRT.M 5\nSTOP.M 15\nSTEP.M 10\nNULL. -999.25\n~Curve\nDEPT.M : MD\nPHI.% : POROSITY\nNTG.V/V : NTG\n~ASCII\n5 22 0.7\n15 18 0.9\n"
    )
    source = LocalSources(service.store).register("Synthetic exchange", folder)
    app = create_app(service=service, with_ui=False, mcp_profile="agent")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as http:
            async with streamable_http_client("http://127.0.0.1:8765/mcp/", http_client=http) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    async def call(operation, **request):
                        reply = await session.call_tool(operation, arguments=dict(request=request))
                        assert not reply.isError, reply.content
                        value = json.loads(reply.content[0].text)
                        assert "error" not in value, value
                        return value["result"]

                    async def job(operation, **request):
                        submitted = await call(operation, **request)
                        for _ in range(1000):
                            record = await call("job_status", job_id=submitted["job_id"])
                            if record["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
                                break
                            await asyncio.sleep(0.05)
                        assert record["status"] == "succeeded", json.dumps(
                            record, ensure_ascii=False, indent=2
                        )
                        obj = await call(
                            "artifact_inspect", project_id=request["project_id"], ref=record["result"]
                        )
                        return obj, {k: obj[k] for k in ("id", "revision")}

                    assessment = await call("folder_assess", source_id=source["id"])
                    assert assessment["confirmation_required"] and not assessment["compute_started"]
                    files = {r["path"]: r for r in assessment["files"]}
                    pid = (
                        await call(
                            "project_create",
                            name="Synthetic copilot integration",
                            crs="LOCAL_METRIC",
                            vertical_datum="TEST",
                        )
                    )["id"]
                    imported, properties = await job(
                        "eclipse_import",
                        project_id=pid,
                        source_id=source["id"],
                        path="model.DATA",
                        file_revision=files["model.DATA"]["file_revision"],
                        crs="LOCAL_METRIC",
                        vertical_datum="TEST",
                        length_unit="m",
                        z_direction="down",
                        assumptions=["Explicit synthetic model, no field reserves"],
                    )
                    assert imported["summary"]["active_cells"] == 4
                    qc, _ = await job(
                        "model_qc", project_id=pid, properties=properties, region_field="FIPNUM"
                    )
                    assert qc["summary"]["validation_status"] == "PASS"
                    trajectory, trajectory_ref = await job(
                        "geodata_import",
                        project_id=pid,
                        source_id=source["id"],
                        path="survey.csv",
                        file_revision=files["survey.csv"]["file_revision"],
                        crs="LOCAL_METRIC",
                        vertical_datum="TEST",
                        length_unit="m",
                        z_direction="up",
                        kind="trajectory",
                        format="mapped_ascii",
                        name="A survey",
                        delimiter=",",
                        columns={k: k for k in ("well_id", "md", "x", "y", "z")},
                        assumptions=["Explicit synthetic XYZ/MD survey"],
                    )
                    upload = await call(
                        "source_upload",
                        project_id=pid,
                        source_id=source["id"],
                        path="well.las",
                        file_revision=files["well.las"]["file_revision"],
                    )
                    log, log_ref = await job(
                        "dataset_import",
                        project_id=pid,
                        upload_id=upload["id"],
                        kind="las",
                        well_id="A",
                        crs="LOCAL_METRIC",
                        vertical_datum="TEST",
                        units={"DEPT": "m", "PHI": "%", "NTG": "fraction"},
                    )
                    logs_report, _ = await job(
                        "wells_vs_model",
                        project_id=pid,
                        properties=properties,
                        trajectory=trajectory_ref,
                        logs=[
                            dict(
                                ref=log_ref,
                                md_curve="DEPT",
                                property_curves=dict(phi="PHI", ntg="NTG"),
                                property_units=dict(phi="percent", ntg="fraction"),
                            )
                        ],
                        region_field="FIPNUM",
                        max_survey_gap_m=21,
                        boundary_policy="lowest_ijk",
                        parameters_confirmed=True,
                        assumptions=["Compare original synthetic samples, no upscaling"],
                    )
                    assert logs_report["summary"]["validation_status"] == "PASS"
                    base = dict(
                        project_id=pid,
                        properties=properties,
                        region_field="FIPNUM",
                        parameters_confirmed=True,
                        assumptions=["Synthetic user explicitly confirms contact, Bo and oil-zone Sg=0"],
                        scenarios=[
                            dict(
                                name="base",
                                regions=[
                                    dict(region_id=r, owc_z_m=-20.0, bo=1.2, oil_gas_saturation=0.0)
                                    for r in (1, 2)
                                ],
                            )
                        ],
                    )
                    report, report_ref = await job("regional_volumes", **base)
                    result = json.loads(service.store.path(report, "report.json").read_text())
                    assert result["tables"]["scenarios"][0]["STOIIP"] == pytest.approx(400)
                    assert result["tables"]["scenarios"][0]["GIIP"] is None
                    diff, _ = await job(
                        "model_diff",
                        project_id=pid,
                        properties=properties,
                        other_properties=properties,
                        region_field="FIPNUM",
                        atol=0,
                        rtol=0,
                    )
                    assert diff["summary"]["status"] == "IDENTICAL"
                    reconciled, _ = await job(
                        "volumes_reconcile",
                        **base,
                        source_id=source["id"],
                        path="volumes.csv",
                        file_revision=files["volumes.csv"]["file_revision"],
                        reference_scenario="base",
                        columns=dict(region_id="region_id", metric="metric", value="value", unit="unit"),
                        metric_definitions=dict(STOIIP="Oil HCPV/Bo standard m3"),
                        reference_region_definition="FIPNUM",
                        relative_tolerance=1e-10,
                    )
                    assert reconciled["summary"]["status"] == "MATCH"
                    parameters = [dict(region_id=1, field="phi", mode="multiplier", low=0.5, high=1.5)]
                    tornado, tornado_ref = await job(
                        "sensitivity_tornado", **base, parameters=parameters, metric="STOIIP"
                    )
                    assert tornado["summary"]["validation_status"] == "PASS"
                    mc, mc_ref = await job(
                        "uncertainty_monte_carlo",
                        **base,
                        parameters=[dict(parameters[0], distribution="uniform")],
                        metric="STOIIP",
                        samples=4,
                        seed=100,
                        correlation=[[1]],
                        correlation_space="gaussian_copula",
                    )
                    assert mc["summary"]["validation_status"] == "PASS"
                    exported, exported_ref = await job(
                        "results_export",
                        project_id=pid,
                        reports=[report_ref, tornado_ref, mc_ref],
                        title="MCP result / Проверка",
                        max_pdf_rows_per_table=100,
                    )
                    assert {"results.xlsx", "results.pdf", "report.json", "report.html"} <= exported[
                        "files"
                    ].keys()
                    assert (
                        json.loads(service.store.path(exported, "report.json").read_text())[
                            "source_statuses"
                        ][0]["validation_status"]
                        == "PASS"
                    )
                    preview = await call("result_preview", project_id=pid, report=exported_ref)
                    assert preview["filename"] == "report.json" and len(preview["files"]) >= 4
                    # All new scientific jobs preserve immutable input dependencies.
                    assert exported["source_ids"] and report["source_ids"]
