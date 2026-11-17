import asyncio
import json
import zipfile
from pathlib import Path

from opensubsurface.mcp.server import create_mcp
from opensubsurface.support import ISSUE_URL, redact

CONFIDENTIAL = ("Secret Field North", "EPSG:23031", "Q:\\Clients\\Acme\\FIELD_X.EGRID", "-2693.25")


def test_redact_paths_emails_and_secrets_but_keep_urls(tmp_path):
    home = tmp_path / "home"
    line = (
        f"open {home}/attempts/a/output and C:\\Users\\Eng\\FIELD.DATA and /srv/data/field.egrid "
        "token=abc123 by eng@example.com viewer http://127.0.0.1:8765/app/ error=QC_FAILED"
    )
    text = redact(line, home)
    assert "<home>/attempts" in text or "<home>" in text
    for leaked in ("FIELD.DATA", "/srv/data", "abc123", "eng@example.com", str(home)):
        assert leaked not in text
    assert "http://127.0.0.1:8765/app/" in text and "QC_FAILED" in text


def test_paths_under_the_user_home_are_redacted():
    text = redact(str(Path.home() / "Clients" / "Acme" / "FIELD_X.DATA"))
    assert "Acme" not in text and "FIELD_X" not in text and text.startswith("~")


def _failed_job(service, project_id):
    payload = dict(
        project_id=project_id,
        contact_z_m=float(CONFIDENTIAL[3]),
        path=CONFIDENTIAL[2],
        execution=dict(device_policy="cpu", precision="float64"),
    )
    job, _ = service.store.put_job("regional_volumes", payload)
    log = service.store.root / "attempts" / job["attempt_id"] / "worker.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        f"Traceback\n  File {service.store.root}/x.py\nreading {CONFIDENTIAL[2]}\nAPI_KEY=sk-live-1\nValueError\n",
        encoding="utf-8",
    )
    service.store.update_job(
        job["id"],
        status="failed",
        stage="Failed",
        error=dict(code="WORKER_CRASH", message=f"worker died reading {CONFIDENTIAL[2]}"),
    )
    return job


def test_support_report_describes_failures_without_field_data(service):
    project = service.invoke(
        "project_create", dict(name=CONFIDENTIAL[0], crs=CONFIDENTIAL[1], vertical_datum="MSL")
    )
    job = _failed_job(service, project["id"])

    result = service.invoke("support_report", dict(jobs=10, log_lines=50))
    assert result["issue_url"] == ISSUE_URL and result["worker_logs_included"] == 1
    path = Path(result["path"])
    assert path.parent == service.store.root / "support" and path.suffix == ".zip"

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        contents = "\n".join(archive.read(n).decode("utf-8") for n in names)
        report = json.loads(archive.read("report.json"))
    assert {"report.json", "README.txt", "startup.log", "viewer.log", f"worker-logs/{job['id']}.log"} <= names
    for leaked in (*CONFIDENTIAL, "sk-live-1", str(service.store.root)):
        assert leaked not in contents, leaked
    row = report["jobs"][-1]
    assert row["operation"] == "regional_volumes" and row["status"] == "failed"
    assert row["error"]["code"] == "WORKER_CRASH"
    assert row["argument_names"] == ["contact_z_m", "execution", "path", "project_id"]
    assert report["store"]["projects"] == 1 and report["versions"]["kanysh-basic"]


def test_internal_failures_point_to_the_support_report(service):
    project = service.invoke("project_create", dict(name="p", vertical_datum="MSL"))
    job = _failed_job(service, project["id"])
    status = service.invoke("job_status", dict(job_id=job["id"]))
    assert "support_report" in status["error"]["remediation"] and ISSUE_URL in status["error"]["remediation"]


def test_support_report_is_a_default_tool_and_diagnostics_links_issues(service):
    tools = {t.name: t for t in asyncio.run(create_mcp(service).list_tools())}
    assert "support_report" in tools and not tools["support_report"].annotations.readOnlyHint
    diagnostics = service.invoke("diagnostics", dict(lines=5))
    assert diagnostics["issue_url"] == ISSUE_URL
