"""Persist evidence and human-readable reports; no model-provided HTML is executed."""

import base64
import html
import json


def write_report(out, title, result):
    text = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2)
    (out / "report.json").write_text(text, encoding="utf-8")
    body = f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>"
    body += "<style>body{font:15px system-ui;color:#17344a;max-width:1200px;margin:30px auto;padding:0 20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6fa;padding:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #dbe5ee;padding:8px;text-align:left}</style>"
    body += f"<h1>{html.escape(title)}</h1>"
    for key in ("status", "validation_status", "scope"):
        if key in result:
            body += f"<p><strong>{html.escape(key)}:</strong> {html.escape(str(result[key]))}</p>"
    for path in sorted(out.glob("*.png")):
        data = base64.b64encode(path.read_bytes()).decode()
        body += f'<h2>{html.escape(path.stem)}</h2><img style="max-width:100%" alt="{html.escape(path.stem)}" src="data:image/png;base64,{data}">'
    items = dict(result)
    items.update(result.get("tables", {}))
    for key, value in items.items():
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            columns = list(dict.fromkeys(k for row in value[:100] for k in row))
            body += (
                f"<h2>{html.escape(key)}</h2><table><tr>"
                + "".join(f"<th>{html.escape(c)}</th>" for c in columns)
                + "</tr>"
            )
            for row in value[:1000]:
                body += (
                    "<tr>"
                    + "".join(f"<td>{html.escape(str(row.get(c, '')))}</td>" for c in columns)
                    + "</tr>"
                )
            body += "</table>"
            if len(value) > 1000:
                body += f"<p>Showing 1000 of {len(value)} rows; full evidence follows.</p>"
    body += "<h2>Full evidence / assumptions</h2><pre>" + html.escape(text) + "</pre>"
    (out / "report.html").write_text(body, encoding="utf-8")
    return {name: out / name for name in ("report.json", "report.html")}
