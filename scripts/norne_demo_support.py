"""Publication-only Norne controls; not an additional scientific import adapter."""

import math
import re
from pathlib import Path


def equil_records(root):
    """Read the pinned Norne EQUIL include and retain exact line evidence."""
    root = Path(root)
    candidates = [root / "full/norne/INCLUDE/PETRO/E3.prop", root / "norne/INCLUDE/PETRO/E3.prop"]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return []
    rows, active = [], False
    for number, raw in enumerate(path.read_text(encoding="latin-1").splitlines(), 1):
        text = raw.split("--", 1)[0].strip()
        if text.upper() == "EQUIL":
            active = True
            continue
        if not active or not text:
            continue
        if re.match(r"^[A-Za-z]", text):
            break
        fields = text.split("/", 1)[0].split()
        if len(fields) < 5:
            raise ValueError("Incomplete explicit Norne EQUIL record")
        rows.append(
            dict(
                region_id=len(rows) + 1,
                owc_depth_m=float(fields[2]),
                goc_depth_m=float(fields[4]),
                file=path.relative_to(root).as_posix(),
                line=number,
            )
        )
    return rows


def contacts(root, minimum_depth, maximum_depth):
    """Three strictly interior alternatives, preferring actual EQUIL OWC values."""
    if not math.isfinite(minimum_depth + maximum_depth) or minimum_depth >= maximum_depth:
        raise ValueError("Finite non-empty active depth range required")
    records = equil_records(root)
    values = sorted({r["owc_depth_m"] for r in records if minimum_depth < r["owc_depth_m"] < maximum_depth})
    if len(values) >= 3:
        lo, hi = values[0], values[-1]
        middle = min(values[1:-1], key=lambda v: abs(v - (lo + hi) / 2))
        selected = [lo, middle, hi]
        source = "EQUIL OWC records; applied uniformly only as static sensitivity alternatives, not regional equilibrium initialization"
    elif records:
        raise ValueError(
            "EQUIL exists but has fewer than three distinct in-range OWCs; no invented contact substitutes"
        )
    else:
        selected = [minimum_depth + (maximum_depth - minimum_depth) * q for q in (0.25, 0.5, 0.75)]
        source = "No EQUIL available; explicit interior 25/50/75 percent depth-range demo alternatives, not probability quantiles"
    return dict(
        depths_m=selected,
        active_depth_range_m=[minimum_depth, maximum_depth],
        source=source,
        evidence=[r for r in records if r["owc_depth_m"] in selected],
    )


def strict_contact_results(rows):
    ordered = sorted(rows, key=lambda row: -row["contact_z_m"])
    values = [row["STOIIP"] for row in ordered]
    assert len(ordered) == 3 and all(math.isfinite(v) and v > 0 for v in values), values
    assert all(a < b for a, b in zip(values, values[1:])), (
        "Contact alternatives must produce strictly different oil volumes"
    )
    return dict(
        status="PASS", contacts_depth_m=[-r["contact_z_m"] for r in ordered], stoiip_standard_m3=values
    )
