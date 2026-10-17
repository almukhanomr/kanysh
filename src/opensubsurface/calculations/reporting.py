import base64
import csv
import html
import json
from pathlib import Path

from opensubsurface.persistence.store import now


def render(context, resolved, out):
    plan = resolved["plan"]
    spec = plan["parameters"]
    from opensubsurface.calculations.planning import compile_nodes

    nodes = compile_nodes(plan)
    expected = [n["id"] for n in nodes if n["operation"] not in ("result_validate", "report_export")]
    missing, failures, checks = [], [], []
    for name in expected:
        artifact, validation = resolved.get(name), resolved.get("check_" + name)
        if artifact is None or validation is None:
            missing.append(name)
            continue
        evidence = json.loads(Path(validation["paths"]["validation.json"]).read_text(encoding="utf-8"))
        target = dict(id=artifact["id"], revision=artifact["revision"], content_hash=artifact["content_hash"])
        if evidence["target"] != target:
            failures.append(dict(node=name, reason="Validation target/hash mismatch"))
        if evidence["status"] == "FAIL":
            failures.append(dict(node=name, reason="Required numerical checks failed"))
        if evidence["status"] == "INCOMPLETE":
            missing.append(name)
        checks.extend(dict(node=name, **check) for check in evidence["checks"])
    unavailable = context.get("unavailable", {})
    status = "FAIL" if failures or unavailable else ("INCOMPLETE" if missing else "PASS")
    rows = []
    for i, contact in enumerate(spec["contacts"]):
        result = resolved.get(f"contact_{i}")
        if result:
            rows.append(dict(name=contact["name"], contact_z_m=contact["z_m"], **result["summary"]["values"]))
    report = dict(
        schema_version=1,
        title=spec["name"],
        run_id=context["run_id"],
        generated_at=now(),
        validation_status=status,
        geological_fitness="REQUIRES_REVIEW",
        scope="Initial oil in place; not recoverable reserves or a production forecast",
        parent_status_at_export=context["parent_status"],
        run_error=context.get("error"),
        missing_nodes=missing,
        failures=failures,
        unavailable_nodes=unavailable,
        contacts=rows,
        checks=checks,
        plan=dict(id=plan["id"], revision=plan["revision"], content_hash=plan["content_hash"]),
        assumptions=spec["assumptions"],
        specification=spec,
        runtime=plan["summary"]["runtime"],
        inputs=plan["summary"]["inputs"],
        evidence={
            name: dict(id=obj["id"], revision=obj["revision"], content_hash=obj["content_hash"])
            for name, obj in resolved.items()
        },
    )
    if "uncertainty" in resolved:
        report["uncertainty"] = resolved["uncertainty"]["summary"]
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    columns = ["name", "contact_z_m", "GRV", "GRV_oil_interval", "NetRockVolume", "PV", "HCPV", "STOIIP"]
    with (out / "volumes.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            safe = dict(row)
            if safe["name"].startswith(("=", "+", "-", "@", "\t", "\r")):
                safe["name"] = "'" + safe["name"]
            writer.writerow(safe)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    uncertain = "uncertainty" in resolved
    fig, axes = plt.subplots(
        1, 2 if uncertain else 1, figsize=(12 if uncertain else 8, 4.5), layout="constrained", squeeze=False
    )
    ax = axes[0, 0]
    if rows:
        ax.bar(range(len(rows)), [r["STOIIP"] for r in rows], color="#157f85")
        ax.set_xticks(range(len(rows)), [r["name"] for r in rows])
        ax.set_ylabel("STOIIP [standard m³]")
        ax.set_xlabel("Explicit OWC scenarios (not probability-weighted)")
    else:
        ax.text(0.5, 0.5, "No completed volumetrics", ha="center", transform=ax.transAxes)
    ax.set_title(f"Initial oil in place — numerical checks: {status}")
    if uncertain:
        samples = json.loads(
            Path(resolved["uncertainty"]["paths"]["samples.json"]).read_text(encoding="utf-8")
        )
        axes[0, 1].hist([r["result"]["STOIIP"] for r in samples], bins=min(15, len(samples)), color="#527a9e")
        for key in ("Q10", "Q50", "Q90"):
            axes[0, 1].axvline(report["uncertainty"]["statistics"][key], linestyle="--", label=key)
        axes[0, 1].set_xlabel("STOIIP [standard m³]")
        axes[0, 1].set_ylabel("Sample count")
        axes[0, 1].set_title(f"Scalar uncertainty; seed={report['uncertainty']['seed']}")
        axes[0, 1].legend()
    fig.savefig(out / "volumes.png", dpi=140)
    plt.close(fig)

    def esc(value):
        return html.escape(str(value))

    table = "<table><tr>" + "".join(f"<th>{esc(c)}</th>" for c in columns) + "</tr>"
    table += (
        "".join("<tr>" + "".join(f"<td>{esc(row[c])}</td>" for c in columns) + "</tr>" for row in rows)
        + "</table>"
    )
    check_table = "<table><tr><th>Node</th><th>Check</th><th>Status</th><th>Evidence</th></tr>"
    check_table += (
        "".join(
            f"<tr><td>{esc(c['node'])}</td><td>{esc(c['id'])}</td><td>{esc(c['status'])}</td><td>{esc(json.dumps({k: v for k, v in c.items() if k not in ('node', 'id', 'status')}, ensure_ascii=False))}</td></tr>"
            for c in checks
        )
        + "</table>"
    )
    image = base64.b64encode((out / "volumes.png").read_bytes()).decode()
    body = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Kanysh Basic report</title>
<style>body{{font:16px system-ui;max-width:1200px;margin:40px auto;padding:0 24px;color:#163447}}table{{border-collapse:collapse;font-size:13px;width:100%}}td,th{{border:1px solid #ccd;padding:7px;text-align:left;overflow-wrap:anywhere}}pre{{white-space:pre-wrap}}img{{max-width:100%}}</style>
<h1>{esc(spec["name"])}</h1><p>Run: {esc(context["run_id"])}</p>
<p><strong>Numerical checks: {status}</strong> · Geological fitness: REQUIRES REVIEW</p>
<p>{esc(report["scope"])}</p><h2>Explicit assumptions</h2><pre>{esc(json.dumps(spec["assumptions"], ensure_ascii=False, indent=2))}</pre>
<h2>Contacts and volumes</h2>{table}<img alt="Initial oil in place by contact" src="data:image/png;base64,{image}">
<h2>Seeded scalar uncertainty</h2><pre>{esc(json.dumps(report.get("uncertainty", {"status": "NOT REQUESTED"}), ensure_ascii=False, indent=2))}</pre>
<h2>Missing / failed</h2><pre>{esc(json.dumps(dict(parent_status=context["parent_status"], run_error=context.get("error"), missing=missing, failures=failures, unavailable=unavailable), ensure_ascii=False, indent=2))}</pre>
<h2>Validation evidence</h2>{check_table}<h2>Inputs and provenance</h2><pre>{esc(json.dumps(dict(plan=report["plan"], inputs=report["inputs"], runtime=report["runtime"]), ensure_ascii=False, indent=2))}</pre>
<p>Full specification, uncertainty statistics and artifact hashes: report.json.</p></html>"""
    (out / "report.html").write_text(body, encoding="utf-8")
    # JSON strings keep untrusted user labels/assumptions delimited as data.
    md = f"# Kanysh Basic calculation report\n\nRun: `{context['run_id']}`\n\nNumerical checks: **{status}**. Geological fitness: **REQUIRES REVIEW**.\n\n{report['scope']}\n\n"
    md += (
        "```json\n"
        + json.dumps(
            dict(contacts=rows, assumptions=spec["assumptions"], missing=missing, failures=failures),
            ensure_ascii=False,
            indent=2,
        )
        + "\n```\n\nSee report.html, report.json, volumes.csv and volumes.png for the full evidence.\n"
    )
    (out / "report.md").write_text(md, encoding="utf-8")
    return (
        "calculation_report",
        dict(
            run_id=context["run_id"],
            validation_status=status,
            geological_fitness="REQUIRES_REVIEW",
            contact_count=len(rows),
            check_count=len(checks),
            missing_nodes=missing,
            failed_nodes=failures,
        ),
        {
            name: out / name
            for name in ("report.html", "report.md", "report.json", "volumes.csv", "volumes.png")
        },
    )
