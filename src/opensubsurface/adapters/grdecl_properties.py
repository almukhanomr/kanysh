"""Strict streaming reader for one exported ECLIPSE property keyword per file.

Geometry is explicitly supplied as uniform Cartesian; full DATA/INCLUDE/COORD/ZCORN are
rejected. Arrays retain ECLIPSE I-fast, K-down order without global transpose buffers.
"""

import math
import os

import numpy as np

from opensubsurface.adapters.local_sources import opened_source, revision
from opensubsurface.errors import require

FORMAT = "opensubsurface.cartesian.grdecl-properties.v1"
KEYWORDS = dict(
    active={"ACTNUM"},
    zones={"FIPNUM", "SATNUM"},
    phi={"PORO"},
    ntg={"NTG"},
    sw={"SWAT"},
    permeability_md={"PERMX"},
    kz_ratio={"PERMZ"},
)


def fill(fd, target, keyword, cells, block_cells, sha, permx=None):
    """Expand runs directly into bounded numeric buffers; no input-sized token lists."""
    buffer = np.empty(min(cells, block_cells), dtype=target.dtype)
    position, filled, started, terminated = 0, 0, False, False
    with os.fdopen(os.dup(fd), "rb") as stream:
        stream.seek(0)
        while line := stream.readline(65537):
            require(len(line) <= 65536, "INVALID_FORMAT", "GRDECL line exceeds 64 KiB")
            sha.update(line)
            text = line.decode("ascii").split("--", 1)[0]
            for token in text.replace("/", " / ").split():
                require(len(token) <= 128, "INVALID_FORMAT", "GRDECL token too long")
                if not started:
                    require(
                        token.upper() == keyword,
                        "UNSUPPORTED_FORMAT",
                        "Expected single exported keyword " + keyword,
                    )
                    started = True
                    continue
                require(not terminated, "UNSUPPORTED_FORMAT", "Extra data/keywords after property terminator")
                if token == "/":
                    terminated = True
                    continue
                if "*" in token:
                    count_text, value_text = token.split("*", 1)
                    require(
                        count_text.isdigit() and bool(value_text),
                        "INVALID_FORMAT",
                        "Implicit GRDECL defaults unsupported",
                    )
                    repeats = int(count_text)
                else:
                    repeats, value_text = 1, token
                require(
                    0 < repeats <= cells - position - filled,
                    "GRID_MAPPING_ERROR",
                    "Wrong property value count",
                )
                try:
                    value = float(value_text.replace("D", "E").replace("d", "e"))
                except ValueError:
                    require(False, "UNSUPPORTED_FORMAT", "Numeric property only; no INCLUDE/geometry/edits")
                require(math.isfinite(value), "QC_FAILED", "Nonfinite GRDECL value")
                if target.dtype.kind in "bui":
                    require(value == math.floor(value), "QC_FAILED", "Integer ACTNUM/region expected")
                    if target.dtype.kind == "b":
                        require(value in (0, 1), "QC_FAILED", "ACTNUM must be 0/1")
                    else:
                        info = np.iinfo(target.dtype)
                        require(info.min <= value <= info.max, "QC_FAILED", "Integer property overflow")
                while repeats:
                    take = min(repeats, len(buffer) - filled)
                    buffer[filled : filled + take] = value
                    filled += take
                    repeats -= take
                    if filled == len(buffer):
                        write(target, position, buffer, permx)
                        position += filled
                        filled = 0
        require(
            started and terminated and position + filled == cells,
            "GRID_MAPPING_ERROR",
            "Property must contain exactly NX*NY*NZ values and trailing /",
        )
        if filled:
            write(target, position, buffer[:filled], permx)


def write(target, start, values, permx):
    if permx is not None:
        horizontal = np.asarray(permx[start : start + len(values)])
        values = np.divide(values, horizontal, out=np.full_like(values, np.nan), where=horizontal > 0)
    target[start : start + len(values)] = values


def import_arrays(context, block_cells, group, create):
    import hashlib

    cells = math.prod(context["manifest"]["grid"]["shape"])
    hashes = {}
    for name in KEYWORDS:
        header = context["headers"][name]
        target = create(
            name, np.dtype("bool" if name == "active" else "int32" if name == "zones" else "float64")
        )
        if header.get("constant") is not None:
            value = header["constant"]
            if name in ("active", "zones"):
                require(
                    value == int(value)
                    and (value in (0, 1) if name == "active" else 1 <= value <= 2**31 - 1),
                    "QC_FAILED",
                    "Invalid integer constant",
                )
            for start in range(0, cells, block_cells):
                target[start : start + min(cells - start, block_cells)] = np.full(
                    min(cells - start, block_cells), value, dtype=target.dtype
                )
            # Immutable manifest pins the explicitly provided constant; no claimed source file hash.
            hashes[name] = hashlib.sha256((name + ":" + repr(value)).encode()).hexdigest()
            continue
        with opened_source(context["source"], header["path"]) as (fd, _):
            require(
                revision(os.fstat(fd)) == header["file_revision"], "SOURCE_CHANGED", "Property file changed"
            )
            sha = hashlib.sha256()
            fill(
                fd,
                target,
                header["keyword"],
                cells,
                block_cells,
                sha,
                permx=group["permeability_md"] if name == "kz_ratio" else None,
            )
            require(
                revision(os.fstat(fd)) == header["file_revision"], "SOURCE_CHANGED", "Property file changed"
            )
            hashes[name] = sha.hexdigest()
    return hashes
