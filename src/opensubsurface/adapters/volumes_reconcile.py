"""Reconcile explicit Petrel/RMS CSV metrics; hypotheses are evidence-labelled, not facts."""

import csv
import hashlib

import numpy as np

from opensubsurface.adapters.regional_volumes import evaluate
from opensubsurface.errors import require

CONVERSIONS = {
    "m3": 1.0,
    "m³": 1.0,
    "sm3": 1.0,
    "std_m3": 1.0,
    "standard_m3": 1.0,
    "rm3": 1.0,
    "stb": 0.158987294928,
    "rb": 0.158987294928,
    "scf": 0.028316846592,
}


def run(obj, p, path, polygon=None):
    result = evaluate(obj, p, polygon)
    require(
        p["reference_scenario"] in {s["name"] for s in p["scenarios"]},
        "INVALID_ARGUMENTS",
        "Reference scenario is not in computed scenarios",
    )
    selected = {
        row["region_id"]: row
        for row in result["tables"]["regions"]
        if row["scenario"] == p["reference_scenario"]
    }
    require(
        {"region_id", "metric", "value", "unit"} <= p["columns"].keys(),
        "INVALID_ARGUMENTS",
        "Map CSV region_id/metric/value/unit columns explicitly",
    )
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        require(
            set(p["columns"].values()) <= set(reader.fieldnames or []),
            "INVALID_FORMAT",
            "Mapped CSV column missing",
        )
        records = []
        seen = set()
        for count, row in enumerate(reader, 2):
            require(count <= 100002, "UNSUPPORTED_PROFILE", "Reference volume CSV limit 100k rows")
            item = {k: row[v] for k, v in p["columns"].items()}
            rid = int(item["region_id"])
            metric = item["metric"].strip()
            require((rid, metric) not in seen, "INVALID_FORMAT", "Duplicate region/metric row")
            seen.add((rid, metric))
            require(
                metric in p["metric_definitions"],
                "NEEDS_INPUT",
                "Confirm reference definition for metric " + metric,
            )
            value = float(item["value"])
            require(np.isfinite(value), "INVALID_FORMAT", "Nonfinite reference value")
            row = dict(
                region_id=rid,
                metric=metric,
                input_value=value,
                input_unit=item["unit"],
                line=count,
                reference_definition=p["metric_definitions"][metric],
            )
            if item["unit"] not in CONVERSIONS or rid not in selected or selected[rid].get(metric) is None:
                row.update(
                    status="NOT RUN",
                    reason="Unsupported unit, missing selected region or metric not calculated",
                    reference_m3=None,
                    computed_m3=None,
                    difference_m3=None,
                    relative_difference=None,
                    probable_causes=[],
                )
            else:
                expected = value * CONVERSIONS[item["unit"]]
                actual = selected[rid][metric]
                delta = actual - expected
                relative = delta / abs(expected) if expected else None
                agrees = abs(relative) <= p["relative_tolerance"] if relative is not None else delta == 0
                row.update(
                    reference_m3=expected,
                    computed_m3=actual,
                    difference_m3=delta,
                    relative_difference=relative,
                    status="MATCH" if agrees else "DIFFERENCE",
                    probable_causes=[],
                )
            records.append(row)
    references = {(r["region_id"], r["metric"]): r for r in records}
    for row in records:
        if row["status"] != "DIFFERENCE":
            continue
        causes = []
        rid, metric = row["region_id"], row["metric"]
        if metric == "STOIIP":
            hcpv = references.get((rid, "HCPV"))
            if hcpv and hcpv["status"] == "MATCH" and row["reference_m3"] > 0:
                implied = hcpv["reference_m3"] / row["reference_m3"]
                causes.append(
                    dict(
                        cause="Bo",
                        evidence=f"HCPV agrees; implied reference Bo={implied:.12g}, explicit model Bo={selected[rid]['bo']}",
                        confidence="supported hypothesis",
                    )
                )
        if metric in {"GRV_oil_interval", "NetRockVolume", "PV", "HCPV", "STOIIP", "GasGRV", "GasPV", "GIIP"}:
            causes.append(
                dict(
                    cause="contact",
                    evidence="Metric depends on explicit OWC/GOC; source-report contacts were not independently supplied",
                    confidence="unverified candidate",
                )
            )
        if metric in {"NetRockVolume", "PV", "HCPV", "STOIIP", "GasPV", "GIIP"}:
            causes.append(
                dict(
                    cause="NTG clipping / pore-volume definition",
                    evidence="Reference may use NTG cutoffs or TotalPV instead of oil-interval PV; compare declared metric definitions",
                    confidence="unverified candidate",
                )
            )
        causes.append(
            dict(
                cause="inactive cells",
                evidence="Calculation uses ACTNUM=1; reference active-cell mask has not been supplied",
                confidence="unverified candidate",
            )
        )
        causes.append(
            dict(
                cause="region definition",
                evidence=f"Computed {p['region_field']}; reference declaration: {p['reference_region_definition']}",
                confidence="unverified candidate",
            )
        )
        row["probable_causes"] = causes
    result.update(
        operation="volumes_reconcile",
        status="INCOMPLETE"
        if any(r["status"] == "NOT RUN" for r in records)
        else "MATCH"
        if all(r["status"] == "MATCH" for r in records)
        else "DIFFERENCES",
        reference=dict(
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            scenario=p["reference_scenario"],
            region_definition=p["reference_region_definition"],
            relative_tolerance=p["relative_tolerance"],
        ),
    )
    require(bool(records), "INVALID_FORMAT", "Empty reference CSV")
    result["tables"]["reconciliation"] = records
    result["limitations"].append(
        "Probable causes are labelled hypotheses; no automatic calibration or interpretation of ambiguous reference metric definitions"
    )
    return result
