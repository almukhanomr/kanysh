"""Viewer discovery for HTTP and separate stdio MCP clients sharing the same store.

Only an active local viewer advertises URLs. No credentials or job execution are involved.
"""

import os
from urllib.parse import quote, urlsplit

import psutil

STATE = "owner:local_viewer"


def register(service, base_url):
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Viewer URL must be local HTTP origin")
    record = dict(
        base_url=base_url.rstrip("/"), pid=os.getpid(), process_created=psutil.Process().create_time()
    )
    service.store.set_state(STATE, record)
    return record


def unregister(service, record):
    if service.store.get_state(STATE, {}) == record:
        service.store.set_state(STATE, {})


def base_url(service):
    record = service.store.get_state(STATE, {})
    try:
        if psutil.Process(record["pid"]).create_time() != record["process_created"]:
            return None
        parsed = urlsplit(record["base_url"])
        if (
            parsed.scheme == "http"
            and parsed.hostname in ("127.0.0.1", "localhost", "::1")
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and parsed.path in ("", "/")
        ):
            return record["base_url"]
    except (KeyError, ValueError, psutil.Error):
        pass
    return None


def artifact_path(project_id, reference):
    return (
        f"/viewer/projects/{quote(project_id, safe='')}/artifacts/"
        f"{quote(reference['id'], safe='')}/{int(reference['revision'])}"
    )


def present(service, result, arguments):
    """Add transient presentation links at the MCP boundary, never to immutable manifests."""
    origin = base_url(service)
    if not origin or not isinstance(result, dict):
        return result
    value = dict(result)
    pid = arguments.get("project_id") or result.get("project_id")
    if not pid:
        return value

    def link(reference):
        if not isinstance(reference, dict) or not {"id", "revision"} <= reference.keys():
            return None
        obj = service.store.object(
            pid, dict(id=reference["id"], revision=reference["revision"]), verify=False
        )
        if obj["kind"] in ("calculation_report", "scene", "analysis_report") or "report.html" in obj["files"]:
            return origin + artifact_path(pid, reference)
        return None

    if result.get("kind") in (
        "calculation_report",
        "scene",
        "analysis_report",
    ) or "report.html" in result.get("files", {}):
        value["viewer_url"] = origin + artifact_path(pid, result)
    for key in ("report", "result"):
        reference = result.get(key)
        if isinstance(reference, dict) and {"id", "revision"} <= reference.keys():
            url = link(reference)
            if url:
                value.setdefault("viewer_links", {})[key] = url
                value["viewer_url"] = url
    return value
