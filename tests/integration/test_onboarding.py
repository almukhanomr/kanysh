import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from opensubsurface.adapters.folder_assess import assess
from opensubsurface.adapters.local_sources import LocalSources
from opensubsurface.api.app import create_app
from opensubsurface.errors import DomainError
from opensubsurface.setup import config_paths, register_config, setup


def test_folder_assessment_proposals_are_line_bound_not_parameters(service, tmp_path):
    folder = tmp_path / "exchange"
    folder.mkdir()
    (folder / "MODEL.DATA").write_text(
        "RUNSPEC\nMETRIC\nGRID\nCOORD\n1 2 3 /\nPROPS\nPORO\n0.2 /\nSOLUTION\nEQUIL\n2500 200 2600 0 2400 0 /\n-- CRS: EPSG:32631\n"
    )
    (folder / "volumes.csv").write_text("region_id,metric,value,unit\n1,STOIIP,123,sm3\n")
    (folder / "survey.csv").write_text("well_id,md,x,y,z\nW,1,2,3,4\n")
    (folder / "logs.las").write_text("~Version\nVERS. 2.0\n")
    (folder / "forbidden.las").symlink_to(tmp_path / "secret.las")
    (folder / ".hidden.DATA").write_text("FIELD\n")
    source = LocalSources(service.store).register("World exchange", folder)
    p = dict(source_id=source["id"], path="", max_depth=2, max_files=200)
    result = assess(service.store, p)
    assert result["validation"]["status"] == "PASS" and result["validation"]["scientific_checks"] == "NOT RUN"
    assert result["compute_started"] is False and result["confirmation_required"] is True
    assert len(result["files"]) == 4
    equil = next(r for r in result["proposals"] if r["parameter"] == "EQUIL")
    assert equil["evidence"] == [
        dict(file="MODEL.DATA", line=10, text="EQUIL"),
        dict(file="MODEL.DATA", line=11, text="2500 200 2600 0 2400 0 /"),
    ]
    assert "bo" not in equil and equil["status"] == "PROPOSAL_REQUIRES_USER_CONFIRMATION"
    assert {"volume_report", "trajectory", "logs"} <= {r for f in result["files"] for r in f["roles"]}
    assert result["export_guide"] == "opensubsurface://docs/petrel-export"
    assert all(r["status"] != "PASS" for r in result["workflows"])
    assert assess(service.store, dict(p, max_files=1))["status"] == "PARTIAL_DISCOVERY"
    LocalSources(service.store).remove(source["id"])
    with pytest.raises(DomainError):
        assess(service.store, p)


def test_setup_backup_idempotency_and_conflict_preserve_other_servers(service, tmp_path):
    desktop, code = tmp_path / "desktop.json", tmp_path / "code.json"
    original = b'{"mcpServers":{"other":{"command":"other"}},"theme":"dark"}'
    desktop.write_bytes(original)
    result = setup(service, desktop, code, start_viewer=False)
    assert Path(result["claude_desktop"]["backup"]).read_bytes() == original
    config = json.loads(desktop.read_text())
    assert config["theme"] == "dark" and config["mcpServers"]["other"] == {"command": "other"}
    assert config["mcpServers"]["kanysh-basic"]["args"][-1] == "agent"
    assert json.loads(code.read_text())["mcpServers"]["kanysh-basic"]["type"] == "stdio"
    assert setup(service, desktop, code, start_viewer=False)["claude_desktop"]["status"] == "UNCHANGED"
    saved = desktop.read_bytes()
    with pytest.raises(DomainError, match="registration differs"):
        register_config(desktop, dict(command="different"))
    assert desktop.read_bytes() == saved
    desktop.write_text("invalid json")
    with pytest.raises(json.JSONDecodeError):
        register_config(desktop, {})
    assert desktop.read_text() == "invalid json"
    assert "Application Support/Claude" in config_paths(tmp_path, "darwin")[0].as_posix()
    assert config_paths(tmp_path, "linux")[0] is None


def test_native_dialog_registers_only_owner_choice_and_cancellation(service, tmp_path):
    from opensubsurface.adapters.folder_dialog import add_folder

    with patch("opensubsurface.adapters.folder_dialog.choose_folder", return_value=None):
        assert add_folder(service.store) == dict(status="CANCELLED", registered=False)
    with patch("opensubsurface.adapters.folder_dialog.choose_folder", return_value=tmp_path):
        result = add_folder(service.store)
    assert result["source"]["root"] == str(tmp_path) and result["read_only"]


@pytest.mark.asyncio
async def test_real_mcp_onboarding_prompts_resource_and_json_preview(service, tmp_path):
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
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "Kanysh Basic"
                    names = {t.name for t in (await session.list_tools()).tools}
                    assert {
                        "start",
                        "folder_assess",
                        "results_export",
                        "model_qc",
                        "regional_volumes",
                        "wells_vs_model",
                        "model_diff",
                        "sensitivity_tornado",
                        "uncertainty_monte_carlo",
                    } <= names
                    assert "source_add" not in names and not any(t.startswith("cloud_") for t in names)
                    prompts = {p.name for p in (await session.list_prompts()).prompts}
                    assert {
                        "begin",
                        "check_model",
                        "regional_volumes",
                        "reconcile_petrel",
                        "tornado_analysis",
                        "compare_versions",
                    } <= prompts
                    greeting = json.loads(
                        (await session.call_tool("start", arguments={"request": {}})).content[0].text
                    )["result"]
                    assert greeting["first_connection"] and not greeting["compute_started"]
                    prompt = await session.get_prompt("regional_volumes")
                    assert (
                        "confirm" in prompt.messages[0].content.text.lower()
                        and "Bo/Bg" in prompt.messages[0].content.text
                    )
                    guide = await session.read_resource("opensubsurface://docs/petrel-export")
                    assert "NOT RUN" in guide.contents[0].text and "Перед расчётом" in guide.contents[0].text
                    pid = service.invoke("project_create", dict(name="preview", vertical_datum="TEST"))["id"]
                    path = tmp_path / "report.json"
                    path.write_text('{"status":"NOT RUN"}')
                    report = service.store.publish(
                        pid, "analysis_report", dict(validation_status="NOT RUN"), {"report.json": path}
                    )
                    response = await session.call_tool(
                        "result_preview",
                        arguments=dict(
                            request=dict(project_id=pid, report={k: report[k] for k in ("id", "revision")})
                        ),
                    )
                    value = json.loads(response.content[0].text)["result"]
                    assert value["filename"] == "report.json" and value["validation_status"] == "NOT RUN"
                    assert not any(c.type == "image" for c in response.content)
                    resource = await session.read_resource(value["resource_uri"])
                    assert resource.contents


def test_mcpb_source_bundle_excludes_data_and_has_no_machine_paths(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "builder", Path(__file__).parents[2] / "scripts/build_mcpb.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    result = builder.build(tmp_path / "test.mcpb")
    assert result["archive_check"] == "PASS" and result["host_installation"] == "NOT RUN"
    with zipfile.ZipFile(result["path"]) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["name"] == "kanysh-basic" and manifest["display_name"] == "Kanysh Basic"
        assert manifest["manifest_version"] == "0.4" and manifest["tools_generated"]
        assert "${user_config.home}" in json.dumps(manifest)
        assert "/Users/" not in bundle.read("server.py").decode()
        assert "experimental" not in json.dumps(bundle.namelist())
        assert b'"gradio' in bundle.read("pyproject.toml")
