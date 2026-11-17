"""Anonymized support report: what a maintainer needs to reproduce a failure, without field data.

The report contains versions, platform, resources, startup/simulator state, recent job
operations/statuses/error codes and redacted log tails. It never contains artifact contents,
project names, CRS/datum, file names from job payloads, argument values, environment
variables or tokens. Logs are redacted for paths, e-mail addresses and secret-like values,
but free text written by third-party libraries can still mention a file name: the owner
reviews the ZIP before attaching it to a public issue.
"""

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ISSUE_URL = "https://github.com/almukhanomr/kanysh/issues/new/choose"
SCHEMA = "kanysh.support-report.v1"
INTERNAL_ERRORS = {"WORKER_CRASH", "COMPUTE_FAILED", "EXECUTOR_FAILED", "WORKFLOW_FAILED", "STARTUP_FAILED"}
SUPPORT_HINT = (
    "If this repeats with valid inputs, run the support_report tool (or `kanysh-basic support-report`) "
    "and attach the ZIP to a GitHub issue: " + ISSUE_URL
)

_SECRET = re.compile(
    r"(?i)(token|password|passwd|secret|authorization|api[_-]?key|bearer)(\s*[=:]\s*|\s+)\S+"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_WINDOWS_PATH = re.compile(r"(?:\\\\\?\\)?(?<![\w])[A-Za-z]:[\\/][^\s\"'<>|]*")
_UNC_PATH = re.compile(r"\\\\[^\s\"'<>|\\]+\\[^\s\"'<>|]*")
# A POSIX path: a slash-separated run that does not continue a URL ("http://host/a"), a word or
# an already redacted "<home>" prefix (paths inside the results home are not sensitive).
_POSIX_PATH = re.compile(r"(?<![\w:/.<>])/(?:[^\s/\"'<>|:]+/)*[^\s/\"'<>|:]+")


def redact(text, home=None):
    """Replace paths, e-mail addresses and secret-like values; keep everything else readable."""
    for root, label in ((home, "<home>"), (Path.home(), "~")):
        if root:
            for spelling in {str(root), str(root).replace("\\", "/")}:
                if len(spelling) > 3:
                    text = text.replace(spelling, label)
    text = _SECRET.sub(r"\1\2<redacted>", text)
    text = _EMAIL.sub("<email>", text)
    text = _UNC_PATH.sub("<path>", text)
    text = _WINDOWS_PATH.sub("<path>", text)
    return _POSIX_PATH.sub("<path>", text)


def _tail(path, lines, home):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 262144))
        text = stream.read().decode("utf-8", errors="replace")
    return [redact(line, home) for line in text.splitlines()[-lines:]]


def _error(error, home):
    if not error:
        return None
    return dict(
        code=error.get("code"),
        message=redact(str(error.get("message", "")), home),
        field=error.get("field"),
    )


def _jobs(store, limit, log_lines, home):
    jobs = store.list_jobs(limit=None)[-limit:]
    rows, logs = [], {}
    for job in jobs:
        attempts = job.get("attempts") or []
        rows.append(
            dict(
                id=job["id"],
                operation=job["operation"],
                status=job["status"],
                stage=redact(str(job.get("stage") or ""), home),
                backend=job.get("backend"),
                created_at=job.get("created_at"),
                completed_at=job.get("completed_at"),
                elapsed_seconds=job.get("elapsed_seconds"),
                attempts=len(attempts),
                attempt_errors=[a["error"]["code"] for a in attempts if a.get("error")],
                error=_error(job.get("error"), home),
                # Argument names only: values can hold field names, contacts and file paths.
                argument_names=sorted((job.get("payload") or {}).keys()),
                execution=(job.get("payload") or {}).get("execution"),
                warnings=[redact(str(w), home) for w in job.get("warnings") or []],
            )
        )
        if job["status"] in ("failed", "interrupted") and job.get("attempt_id"):
            log = store.root / "attempts" / job["attempt_id"] / "worker.log"
            tail = _tail(log, log_lines, home)
            if tail:
                logs[job["id"]] = tail
    return rows, logs


def _inventory(store):
    from collections import Counter

    projects = store.list_projects()
    kinds = Counter()
    for project in projects:
        for obj in store.list_objects(project["id"], limit=None):
            kinds[obj["kind"]] += 1
    return dict(projects=len(projects), artifacts_by_kind=dict(sorted(kinds.items())))


def build(target, p, now=None):
    """Write <home>/support/kanysh-support-<UTC time>.zip and return its path and a content summary."""
    from opensubsurface.diagnostics import _simulator, _versions
    from opensubsurface.execution.resources import inventory

    runtime = target if hasattr(target, "require_ready") else None
    service = getattr(runtime, "service", None) if runtime else target
    home = Path(runtime.home if runtime else service.store.root).resolve()
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    report = dict(
        schema=SCHEMA,
        created_at=(now or datetime.now(timezone.utc)).isoformat(),
        versions=_versions(),
        resources=inventory(home),
        simulator=json.loads(redact(json.dumps(_simulator(home)), home)),
        startup=None,
        store=None,
        jobs=[],
        excluded=(
            "artifact contents, project names, CRS/datum, argument values, file names from job payloads, "
            "environment variables and tokens"
        ),
    )
    if runtime is not None:
        with runtime.lock:
            report["startup"] = dict(
                stage=runtime.stage,
                substage=runtime.substage,
                error=redact(str(runtime.error), home) if runtime.error else None,
                service_ready=runtime.service_ready.is_set(),
                ready=runtime.ready.is_set(),
            )
            cuda = runtime.details.get("runtime")
        report["cuda"] = cuda
    logs = {}
    if service is not None:
        try:
            report["store"] = _inventory(service.store)
            report["jobs"], logs = _jobs(service.store, p["jobs"], p["log_lines"], home)
        except Exception as error:  # A broken store is exactly what a support report must still describe.
            report["store"] = dict(error=type(error).__name__)
    else:
        report["store"] = dict(status="NOT AVAILABLE", note="service did not start; see startup and logs")
    files = {
        "report.json": json.dumps(report, indent=2, ensure_ascii=False, default=str),
        "startup.log": "\n".join(_tail(home / "startup.log", p["log_lines"], home)),
        "viewer.log": "\n".join(_tail(home / "viewer.log", p["log_lines"], home)),
        "README.txt": (
            "Kanysh Basic support report (" + SCHEMA + ").\n"
            "Contains: versions, platform, resources, startup/simulator state, recent job operations,\n"
            "statuses, error codes and redacted log tails.\n"
            "Excluded: " + report["excluded"] + ".\n"
            "Paths, e-mail addresses and secret-like values are replaced with <path>, <email>, <redacted>.\n"
            "Please read the files before attaching this ZIP to a public issue: " + ISSUE_URL + "\n"
        ),
    }
    for job_id, tail in logs.items():
        files[f"worker-logs/{job_id}.log"] = "\n".join(tail)
    directory = home / "support"
    directory.mkdir(exist_ok=True)
    path = directory / f"kanysh-support-{stamp}.zip"
    temporary = path.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    temporary.replace(path)
    return dict(
        path=str(path),
        size_bytes=path.stat().st_size,
        files=sorted(files),
        jobs_included=len(report["jobs"]),
        worker_logs_included=len(logs),
        excluded=report["excluded"],
        issue_url=ISSUE_URL,
        next_step=(
            "Ask the user to open the ZIP, check it contains nothing confidential, then attach it to a "
            "new issue at issue_url. Nothing has been sent anywhere."
        ),
    )
