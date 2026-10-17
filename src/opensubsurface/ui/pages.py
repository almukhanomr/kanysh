"""Read-only, stable viewer pages used by links from MCP clients."""

import html
import json
from urllib.parse import quote

from fastapi.responses import FileResponse, HTMLResponse

from opensubsurface.errors import DomainError
from opensubsurface.viewer_links import artifact_path


def layout(title, body):
    return HTMLResponse(f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{font:16px system-ui;background:#f3f6fa;color:#17344a;margin:0}}main{{max-width:1280px;margin:auto;padding:24px}}
a{{color:#087c87}}nav{{display:flex;gap:20px;margin-bottom:24px}}table{{width:100%;border-collapse:collapse;background:white}}
td,th{{text-align:left;padding:12px;border-bottom:1px solid #e0e8ee}}iframe{{width:100%;height:76vh;border:1px solid #dbe5ee;background:white}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:18px}}.muted{{color:#577082}}h1{{font-size:28px}}</style>
<main><nav><a href="/app/">Viewer</a><a href="/viewer/">Projects and revisions</a></nav>{body}</main></html>""")


def mount_pages(app, service):
    @app.get("/viewer/", response_class=HTMLResponse)
    def projects_page():
        rows = "".join(
            f'<tr><td><a href="/viewer/projects/{quote(p["id"], safe="")}">{html.escape(p["name"])}</a></td>'
            f"<td>{html.escape(p['crs'])}</td><td>{html.escape(p['vertical_datum'])}</td></tr>"
            for p in service.store.list_projects()
        )
        return layout(
            "Projects",
            '<h1>Projects</h1><p class="muted">Run calculations through MCP / CLI / REST.</p>'
            "<table><tr><th>Project</th><th>CRS</th><th>Datum</th></tr>" + rows + "</table>",
        )

    @app.get("/viewer/projects/{project_id}", response_class=HTMLResponse)
    def project_page(project_id: str, offset: int = 0):
        project = service.store.project(project_id)
        offset = max(0, offset)
        objects = service.store.list_objects(project_id, 100, offset)
        rows = "".join(
            f'<tr><td><a href="{artifact_path(project_id, o)}">{html.escape(o["kind"])}</a></td>'
            f"<td>{html.escape(o['id'])}</td><td>{o['revision']}</td><td>{o['content_hash'][:16]}</td></tr>"
            for o in objects
        )
        more = f'<p><a href="?offset={offset + 100}">Next revisions</a></p>' if len(objects) == 100 else ""
        return layout(
            project["name"],
            "<h1>" + html.escape(project["name"]) + "</h1>"
            "<table><tr><th>Artifact</th><th>ID</th><th>Revision</th><th>SHA-256</th></tr>"
            + rows
            + "</table>"
            + more,
        )

    @app.get("/viewer/projects/{project_id}/artifacts/{object_id}/{revision}", response_class=HTMLResponse)
    def artifact_page(project_id: str, object_id: str, revision: int):
        obj = service.store.object(project_id, dict(id=object_id, revision=revision))
        path = artifact_path(project_id, obj)
        title = obj["kind"] + " · r" + str(revision)
        body = f'<h1>{html.escape(title)}</h1><p class="muted">{html.escape(object_id)} · SHA-256 {obj["content_hash"]}</p>'
        name = (
            "scene.html"
            if obj["kind"] == "scene"
            else "report.html"
            if "report.html" in obj["files"]
            else None
        )
        if name and name in obj["files"]:
            body += f'<iframe title="{html.escape(title)}" src="{path}/content/{name}" sandbox="allow-scripts allow-downloads"></iframe>'
        links = " ".join(
            f'<a href="/api/v1/projects/{quote(project_id, safe="")}/artifacts/{quote(object_id, safe="")}/{revision}/files/{quote(name, safe="")}">{html.escape(name)}</a>'
            for name in obj["files"]
        )
        body += "<p>" + links + "</p><details><summary>Metadata and provenance</summary><pre>"
        body += html.escape(json.dumps(obj, ensure_ascii=False, indent=2)) + "</pre></details>"
        return layout(title, body)

    @app.get("/viewer/projects/{project_id}/artifacts/{object_id}/{revision}/content/{name}")
    def artifact_content(project_id: str, object_id: str, revision: int, name: str):
        obj = service.store.object(project_id, dict(id=object_id, revision=revision))
        expected = (
            "scene.html"
            if obj["kind"] == "scene"
            else "report.html"
            if "report.html" in obj["files"]
            else None
        )
        if name != expected:
            raise DomainError("PERMISSION_DENIED", "Only generated report/scene HTML can be rendered")
        return FileResponse(
            service.store.path(obj, name),
            media_type="text/html",
            content_disposition_type="inline",
            headers={
                "Content-Security-Policy": "sandbox allow-scripts allow-downloads; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob:; style-src 'unsafe-inline'; img-src data: blob:; connect-src data: blob:; worker-src blob:"
            },
        )
