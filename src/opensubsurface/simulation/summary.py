"""Portable reader for unformatted ECLIPSE/OPM summary files (SMSPEC + UNSMRY or Snnnn).

Pure NumPy, so results are readable on Windows where resdata/opm-common wheels are absent.
Formatted (FSMSPEC/FUNSMRY) files are rejected explicitly.
"""

import re
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from opensubsurface.errors import require

SIZES = {b"INTE": 4, b"REAL": 4, b"LOGI": 4, b"DOUB": 8, b"CHAR": 8, b"MESS": 0}
NUMERIC = {b"INTE": "i4", b"REAL": "f4", b"LOGI": "i4", b"DOUB": "f8"}


def arrays(path):
    """Yield (keyword, values) for every array of one unformatted ECLIPSE file."""
    with Path(path).open("rb") as stream:
        endian = None
        while marker := stream.read(4):
            require(len(marker) == 4, "INVALID_FORMAT", f"{Path(path).name}: truncated record marker")
            if endian is None:
                require(
                    marker in (struct.pack(">i", 16), struct.pack("<i", 16)),
                    "INVALID_FORMAT",
                    f"{Path(path).name}: not an unformatted ECLIPSE file (formatted files unsupported)",
                )
                endian = ">" if marker == struct.pack(">i", 16) else "<"
            head = stream.read(16)
            require(len(head) == 16 and stream.read(4) == marker, "INVALID_FORMAT", "Corrupt array header")
            name = head[:8].decode("ascii", "replace").strip()
            count = struct.unpack(endian + "i", head[8:12])[0]
            kind = head[12:16]
            if re.fullmatch(rb"C0\d\d", kind):
                size = int(kind[2:])
            else:
                require(kind in SIZES, "INVALID_FORMAT", f"Unsupported ECLIPSE type {kind!r}")
                size = SIZES[kind]
            require(count >= 0, "INVALID_FORMAT", f"Negative count for {name}")
            remaining, chunks = count * size, []
            while remaining:
                record = stream.read(4)
                require(len(record) == 4, "INVALID_FORMAT", f"Truncated {name}")
                length = struct.unpack(endian + "i", record)[0]
                require(0 < length <= remaining, "INVALID_FORMAT", f"Invalid record length in {name}")
                raw = stream.read(length)
                require(len(raw) == length and stream.read(4) == record, "INVALID_FORMAT", f"Corrupt {name}")
                chunks.append(raw)
                remaining -= length
            raw = b"".join(chunks)
            if kind in NUMERIC:
                values = np.frombuffer(raw, dtype=endian + NUMERIC[kind]).copy()
            elif size:
                values = [
                    raw[i : i + size].decode("ascii", "replace").strip() for i in range(0, len(raw), size)
                ]
            else:
                values = []
            yield name, values


def _data_files(smspec):
    smspec = Path(smspec)
    unified = smspec.with_suffix(".UNSMRY")
    if unified.is_file():
        return [unified]
    split = sorted(smspec.parent.glob(smspec.stem + ".S[0-9][0-9][0-9][0-9]"))
    require(bool(split), "INCOMPLETE_OUTPUT", f"No UNSMRY or Snnnn data next to {smspec.name}")
    return split


def read(smspec):
    """Return start date, vector keys/units and the full (steps x vectors) PARAMS matrix."""
    spec = {}
    for name, values in arrays(smspec):
        spec.setdefault(name, values)
    require("KEYWORDS" in spec and "UNITS" in spec, "INVALID_FORMAT", "SMSPEC lacks KEYWORDS/UNITS")
    keywords = spec["KEYWORDS"]
    names = spec.get("NAMES", spec.get("WGNAMES", [""] * len(keywords)))
    nums = spec.get("NUMS", np.zeros(len(keywords), dtype=int))
    start = spec.get("STARTDAT")
    require(start is not None and len(start) >= 3, "INVALID_FORMAT", "SMSPEC lacks STARTDAT")
    day, month, year = (int(v) for v in start[:3])
    hour, minute, micro = (int(v) for v in (list(start[3:6]) + [0, 0, 0])[:3])
    started = datetime(year, month, day, hour, minute, tzinfo=timezone.utc) + timedelta(microseconds=micro)
    keys = []
    for keyword, wgname, num in zip(keywords, names, nums):
        wgname = wgname if wgname not in ("", ":+:+:+:+") else ""
        if keyword.startswith(("W", "G")) and wgname:
            keys.append(f"{keyword}:{wgname}")
        elif keyword.startswith(("B", "R", "C")) and int(num) > 0:
            keys.append(f"{keyword}:{int(num)}")
        else:
            keys.append(keyword)
    rows = []
    for path in _data_files(smspec):
        for name, values in arrays(path):
            if name == "PARAMS":
                require(len(values) == len(keywords), "INVALID_FORMAT", "PARAMS length differs from SMSPEC")
                rows.append(np.asarray(values, dtype=np.float64))
    require(bool(rows), "INCOMPLETE_OUTPUT", "Summary contains no time steps")
    data = np.vstack(rows)
    require("TIME" in keywords, "INVALID_FORMAT", "Summary lacks TIME (days)")
    days = data[:, keywords.index("TIME")]
    require(bool(np.all(np.diff(days) >= 0)), "INVALID_RESULTS", "Summary TIME is not monotonic")
    return dict(
        start=started.isoformat(),
        keys=keys,
        units=list(spec["UNITS"]),
        days=days,
        data=data,
    )


def vector(summary, key):
    require(key in summary["keys"], "MISSING_VECTOR", f"Summary vector {key} not present")
    return summary["data"][:, summary["keys"].index(key)]


def compare(result, reference, keys, relative_tolerance):
    """Compare vectors on the result's report times (reference linearly interpolated in days).

    Deviation is max|result - reference| / max(max|reference|, tiny) over the common time range,
    plus the relative difference at the final common time. No tuning, no shifting.
    """
    require(
        result["start"] == reference["start"], "START_DATE_MISMATCH", "Summaries start on different dates"
    )
    end = min(result["days"][-1], reference["days"][-1])
    mask = result["days"] <= end + 1e-9
    rows = []
    for key in keys:
        if key not in result["keys"] or key not in reference["keys"]:
            rows.append(dict(vector=key, status="NOT RUN", reason="vector absent in result or reference"))
            continue
        ours = vector(result, key)[mask]
        theirs = np.interp(result["days"][mask], reference["days"], vector(reference, key))
        scale = max(float(np.max(np.abs(theirs))), np.finfo(float).tiny)
        deviation = float(np.max(np.abs(ours - theirs)) / scale)
        final = float(abs(ours[-1] - theirs[-1]) / max(abs(float(theirs[-1])), np.finfo(float).tiny))
        rows.append(
            dict(
                vector=key,
                unit=result["units"][result["keys"].index(key)],
                result_final=float(ours[-1]),
                reference_final=float(theirs[-1]),
                final_relative_difference=final,
                max_normalized_deviation=deviation,
                relative_tolerance=relative_tolerance,
                status="PASS" if deviation <= relative_tolerance else "DIFFERENCE",
            )
        )
    return dict(common_end_day=float(end), vectors=rows)
