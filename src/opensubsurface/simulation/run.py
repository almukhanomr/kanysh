"""Worker side of simulation_deck_run: snapshot, run OPM Flow, read and (optionally) compare.

The deck is the user's, copied byte-for-byte; nothing is generated, defaulted or rewritten.
"""

import json
import math
import re
import subprocess
import time
from pathlib import Path

from opensubsurface.errors import require
from opensubsurface.execution import progress
from opensubsurface.simulation import deck as decks
from opensubsurface.simulation import runtime, summary

FIELD_VECTORS = ("FOPT", "FWPT", "FGPT", "FWIT", "FGIT", "FOPR", "FWPR", "FGPR", "FPR")


def _report_days(text):
    """Number of DATES/TSTEP report records, for progress only (never used for results)."""
    return len(re.findall(r"^\s*\d{1,2}\s+'?[A-Za-z]{3}'?\s+\d{4}", text, re.M))


def _watch(process, log_path, total_reports, cancel_file, timeout):
    """Wait for flow; report progress from 'Report step' lines; honour cancel/timeout."""
    started, seen = time.monotonic(), 0
    while process.poll() is None:
        if cancel_file.exists() or time.monotonic() - started > timeout:
            process.terminate()
            return "cancelled" if cancel_file.exists() else "timeout"
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")[-200000:]
            steps = re.findall(r"Report step\s+(\d+)", text)
            if steps:
                seen = max(seen, int(steps[-1]))
        except OSError:
            pass
        if total_reports:
            progress.report(0.05 + 0.85 * min(seen / total_reports, 1.0), f"OPM Flow report step {seen}")
        time.sleep(1.0)
    return "finished"


def run_deck(request, out):
    p, context = request["payload"], request["source_context"]
    home = Path(request["home"])
    pinned = runtime.verify_pin(home)
    work = out / "deck"
    work.mkdir(parents=True)
    hashes = decks.snapshot(context["source"], context["closure"], work)
    progress.report(0.03, "deck snapshot copied", force=True)
    main = work.joinpath(*Path(p["path"]).parts)
    # Report dates may live in INCLUDE files (e.g. Norne's .SCH); count over the whole closure.
    total_reports = sum(
        _report_days(path.read_text(encoding="latin-1")) for path in work.rglob("*") if path.is_file()
    )
    log_path = out / "flow.log"
    attempt = out.parent
    with log_path.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            runtime.command(pinned["executor"], main, "results", p["threads"], p["parsing_strictness"]),
            cwd=main.parent,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env=runtime.WSL_ENV,
        )
        (attempt / "flow-process.json").write_text(
            json.dumps(dict(pid=process.pid, executor=pinned["executor"])), encoding="utf-8"
        )
        try:
            outcome = _watch(
                process, log_path, total_reports, attempt / "cancel", p["execution"]["timeout_seconds"]
            )
        finally:
            if process.poll() is None:
                process.terminate()
            runtime.kill_external(main.parent)
    results = main.parent / "results"
    stem = main.stem
    require(outcome == "finished", "CANCELLED" if outcome == "cancelled" else "TIMEOUT", "OPM Flow stopped")
    full_log = log_path.read_text(encoding="utf-8", errors="replace")
    log_tail = full_log[-4000:]
    # Surface OPM's own first fatal input message (keyword, file, line) instead of a bare exit code.
    fatal = re.search(r"Unrecoverable errors while loading input:\s*\n((?:.*\n){1,4})", full_log)
    reason = " ".join(fatal[1].split()) if fatal else f"exit code {process.returncode}"
    require(
        process.returncode == 0,
        "COMPUTE_FAILED",
        f"OPM Flow stopped: {reason[:400]}; see flow.log and {stem}.PRT/.DBG",
        "path",
        "Read job_logs (flow.log, PRT, DBG). The deck is run exactly as supplied; fix it in the source.",
        dict(flow_log_tail=log_tail),
    )
    smspec = results / f"{stem}.SMSPEC"
    require(smspec.is_file(), "INCOMPLETE_OUTPUT", "Flow wrote no SMSPEC (add a SUMMARY section to the deck)")
    data = summary.read(smspec)
    progress.report(0.93, "summary read", force=True)
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"DAYS": data["days"], **{k: data["data"][:, i] for i, k in enumerate(data["keys"])}})
    pq.write_table(table, out / "summary.parquet")
    final = {
        key: dict(value=float(summary.vector(data, key)[-1]), unit=data["units"][data["keys"].index(key)])
        for key in FIELD_VECTORS
        if key in data["keys"]
    }
    require(
        all(math.isfinite(v["value"]) for v in final.values()), "INVALID_RESULTS", "Nonfinite field vectors"
    )
    comparison = None
    if p.get("reference"):
        reference_dir = out / "reference"
        reference_hashes = decks.snapshot(context["source"], context["reference_files"], reference_dir)
        hashes.update({"reference:" + k: v for k, v in reference_hashes.items()})
        ref = summary.read(reference_dir.joinpath(*Path(p["reference"]["smspec_path"]).parts))
        comparison = dict(
            summary.compare(data, ref, p["reference"]["vectors"], p["reference"]["relative_tolerance"]),
            reference=p["reference"],
            definition="max |result - reference| / max |reference| over the common period; reference "
            "linearly interpolated to result report times",
        )
    statuses = [row["status"] for row in (comparison or {}).get("vectors", [])]
    # Keywords OPM did not apply (reported by OPM itself); with parsing_strictness=low it continued.
    ignored = sorted(
        set(re.findall(r"^\s+([A-Z][A-Z0-9_-]*)(?:\([^)]*\))?: [^\n]*not supported", full_log, re.M))
    )
    relaxed = p["parsing_strictness"] == "low"
    report = dict(
        operation="simulation_deck_run",
        status="PASS",
        scope="User deck run as supplied in OPM Flow; no deck generation or parameter defaults",
        solver=pinned,
        deck=dict(main=p["path"], files=len(hashes), sha256=hashes),
        start_date=data["start"],
        final_day=float(data["days"][-1]),
        report_steps=int(len(data["days"])),
        vectors=len(data["keys"]),
        field_final=final,
        comparison=comparison,
        parsing_strictness=p["parsing_strictness"],
        keywords_not_applied_by_opm=ignored,
        validation_status=(
            "NOT RUN"
            if comparison is None
            else "FAIL"
            if "DIFFERENCE" in statuses
            else ("PASS_WITH_IGNORED_KEYWORDS" if relaxed and ignored else "PASS")
            if statuses and all(s == "PASS" for s in statuses)
            else "INCOMPLETE"
        ),
        limitations=[
            "Results are OPM Flow's for this deck; geological and engineering fitness need specialist review",
            "Comparison metrics are reported as computed; tolerances are the user's explicit choice",
        ]
        + (
            [
                "parsing_strictness=low: OPM ignored these keywords, so the simulated model differs from the deck: "
                + ", ".join(ignored)
            ]
            if relaxed and ignored
            else []
        ),
        assumptions=p["assumptions"],
    )
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    from opensubsurface.adapters.copilot_report import write_report

    files = write_report(out, "OPM Flow deck run", report)
    files.update({"summary.parquet": out / "summary.parquet", "flow.log": log_path})
    for suffix in ("SMSPEC", "UNSMRY", "PRT", "DBG", "EGRID", "INIT"):
        path = results / f"{stem}.{suffix}"
        if path.is_file():
            files[path.name] = path
    if p["keep_restart"]:
        for path in results.glob(f"{stem}.UNRST"):
            files[path.name] = path
    progress.report(1.0, "simulation results published", force=True)
    return (
        "simulation_result",
        dict(
            operation="simulation_deck_run",
            backend="opm-" + pinned["executor"],
            solver=dict(
                (k, pinned.get(k)) for k in ("executor", "flow_version", "flow_sha256", "package_version")
            ),
            final_day=report["final_day"],
            field_final=final,
            validation_status=report["validation_status"],
            start_date=data["start"],
        ),
        files,
    )
