"""Revision-bound, bounded unformatted ECLIPSE reader (global EGRID + INIT).

Fortran records are checked before decoding. Numeric arrays go to disk maps;
neither XTGeo nor input-sized Python buffers participate in the import.
"""

import hashlib
import math
import os
import struct

import numpy as np

from opensubsurface.adapters.eclipse_deck import ARRAYS, Interpreter, discard_pages
from opensubsurface.adapters.local_sources import opened_source, revision
from opensubsurface.errors import require
from opensubsurface.execution.resources import disk_check

TYPES = {b"INTE": "i4", b"REAL": "f4", b"DOUB": "f8", b"LOGI": "i4", b"CHAR": "S8", b"MESS": "S1"}


def records(stream):
    """Yield header and bounded pieces, including empty records; reject corruption."""
    endian = None
    while marker := stream.read(4):
        require(len(marker) == 4, "INVALID_FORMAT", "Truncated Fortran marker")
        if endian is None:
            endian = ">" if marker == struct.pack(">i", 16) else "<"
        require(struct.unpack(endian + "i", marker)[0] == 16, "INVALID_FORMAT", "Expected 16-byte ECL header")
        raw = stream.read(16)
        require(len(raw) == 16 and stream.read(4) == marker, "INVALID_FORMAT", "Truncated ECL header")
        key, count, kind = (
            raw[:8].decode("ascii").strip(),
            struct.unpack(endian + "i", raw[8:12])[0],
            raw[12:],
        )
        require(count >= 0 and kind in TYPES, "UNSUPPORTED_PROFILE", f"Unsupported ECL type {kind!r}")
        dtype = np.dtype(TYPES[kind] if kind in (b"CHAR", b"MESS") else endian + TYPES[kind])
        require(kind != b"MESS" or count == 0, "INVALID_FORMAT", "MESS must be empty")
        yield key, count, dtype, None
        remaining = count * dtype.itemsize
        while remaining:
            head = stream.read(4)
            require(len(head) == 4, "INVALID_FORMAT", f"Truncated {key} record")
            length = struct.unpack(endian + "i", head)[0]
            require(
                0 < length <= min(remaining, 16 * 1024**2) and length % dtype.itemsize == 0,
                "INVALID_FORMAT",
                f"Invalid bounded {key} record length",
            )
            raw = stream.read(length)
            require(len(raw) == length and stream.read(4) == head, "INVALID_FORMAT", f"Corrupt {key} record")
            remaining -= length
            yield key, count, dtype, np.frombuffer(raw, dtype=dtype)


class _HashedStream:
    def __init__(self, stream, sha):
        self.stream, self.sha = stream, sha

    def read(self, size):
        raw = self.stream.read(size)
        self.sha.update(raw)
        return raw


def read_file(deck, path, expected, geometry=False):
    metadata = {"FILEHEAD", "GRIDHEAD", "MAPAXES", "GRIDUNIT", "MAPUNITS", "INTEHEAD"}
    key, pieces, target, position, active_only = None, [], None, 0, False
    active_positions = None
    dirty_low, dirty_high, released = None, 0, 0

    def finish():
        nonlocal active_positions
        if key is None:
            return
        if target is not None:
            deck.arrays[key] = discard_pages(target, dirty=(dirty_low or 0, dirty_high))
        if key not in metadata:
            return
        values = np.concatenate(pieces) if pieces else np.array([])
        if key == "FILEHEAD":
            require(
                len(values) >= 7 and values[4] == 0 and values[5] == 0,
                "UNSUPPORTED_PROFILE",
                "Single-porosity global corner-point EGRID required",
            )
        elif key == "GRIDHEAD":
            require(
                len(values) >= 33 and values[0] == 1 and values[24] == 1 and values[26] == 0,
                "UNSUPPORTED_PROFILE",
                "One Cartesian-coordinate reservoir required; no cylindrical grids",
            )
            shape = tuple(map(int, values[1:4]))
            require(
                all(0 < n <= 1_000_000 for n in shape) and math.prod(shape) <= 500_000_000,
                "GRID_MAPPING_ERROR",
                "Invalid EGRID dimensions",
            )
            require(deck.shape in (None, shape), "GRID_MAPPING_ERROR", "Conflicting GRIDHEAD")
            deck.shape = shape
            disk_check(deck.out, math.prod(shape) * 1024)
        elif key == "MAPAXES":
            require(len(values) == 6 and np.isfinite(values).all(), "INVALID_GEOMETRY", "Invalid MAPAXES")
            deck.mapaxes = values.tolist()
        elif key in {"GRIDUNIT", "MAPUNITS"}:
            deck.suggestions.append(dict(parameter=key, tokens=[v.decode("ascii").strip() for v in values]))
        elif key == "INTEHEAD":
            require(len(values) >= 12, "INVALID_FORMAT", "Truncated INIT INTEHEAD")
            require(
                tuple(map(int, values[8:11])) == deck.shape, "GRID_MAPPING_ERROR", "INIT dimensions differ"
            )
            unit = {1: "METRIC", 2: "FIELD", 3: "LAB"}.get(int(values[2]))
            require(unit is not None, "INVALID_UNITS", "Unknown INIT unit system")
            deck.unit = unit

    with opened_source(deck.source, path) as (fd, _):
        before = revision(os.fstat(fd))
        require(before == expected, "SOURCE_CHANGED", "Binary/property source changed")
        sha = hashlib.sha256()
        with os.fdopen(os.dup(fd), "rb") as raw:
            for name, count, dtype, piece in records(_HashedStream(raw, sha)):
                if piece is None:
                    finish()
                    key, pieces, target, position = name, [], None, 0
                    dirty_low, dirty_high, released = None, 0, 0
                    require(
                        name not in {"LGR", "COORDSYS", "HOSTNUM"},
                        "UNSUPPORTED_PROFILE",
                        f"{name}: only one unrefined global grid is supported",
                    )
                    if name in ARRAYS:
                        require(
                            (name in {"COORD", "ZCORN", "ACTNUM"}) == geometry
                            or (geometry and name not in {"COORD", "ZCORN"}),
                            "UNSUPPORTED_PROFILE",
                            "INIT cannot replace geometry/ACTNUM",
                        )
                        require(name not in deck.arrays, "INVALID_FORMAT", f"Duplicate property {name}")
                        require(dtype.kind in "if", "INVALID_FORMAT", f"Numeric {name} required")
                        target = deck.array(name)
                        active_only = count != len(target) and not geometry
                        if active_only:
                            if name.endswith("NUM"):
                                # Zero is an unavailable-region sentinel only for inactive cells.
                                for start in range(0, len(target), 65536):
                                    target[start : start + 65536] = 0
                                    target = deck.arrays[name] = discard_pages(
                                        target, dirty=(start, min(start + 65536, len(target)))
                                    )
                            require(
                                "ACTNUM" in deck.arrays,
                                "MISSING_PROPERTY",
                                "ACTNUM needed for active INIT properties",
                            )
                            # Store positions on disk as well, without a full-grid integer array.
                            if active_positions is None:
                                nactive = 0
                                active_positions = np.memmap(
                                    deck.out / "active-indices.bin",
                                    mode="w+",
                                    dtype="i8",
                                    shape=(math.prod(deck.shape),),
                                )
                                for start in range(0, len(target), 65536):
                                    ids = (
                                        np.flatnonzero(deck.arrays["ACTNUM"][start : start + 65536] == 1)
                                        + start
                                    )
                                    active_positions[nactive : nactive + len(ids)] = ids
                                    nactive += len(ids)
                                    active_positions = discard_pages(
                                        active_positions, dirty=(nactive - len(ids), nactive)
                                    )
                                    deck.arrays["ACTNUM"] = discard_pages(
                                        deck.arrays["ACTNUM"], readonly=True
                                    )
                                deck._active_count = nactive
                            require(
                                count == deck._active_count,
                                "GRID_MAPPING_ERROR",
                                f"{name} count differs from active cells",
                            )
                        else:
                            require(count == len(target), "GRID_MAPPING_ERROR", f"Wrong {name} count")
                    elif name in metadata:
                        require(count <= 1024, "INVALID_FORMAT", "Unbounded ECL metadata")
                    elif count:
                        deck.unsupported.append(
                            dict(
                                keyword=name,
                                section="EGRID" if geometry else "INIT",
                                file=path,
                                reason="Not applied",
                            )
                        )
                elif target is not None:
                    require(np.isfinite(piece).all(), "INVALID_PROPERTY", f"Nonfinite binary {key}")
                    for start in range(0, len(piece), 65536):
                        values = piece[start : start + 65536]
                        if active_only:
                            indices = active_positions[position : position + len(values)]
                            target[indices] = values
                            low, high = int(indices[0]), int(indices[-1]) + 1
                        else:
                            low, high = position, position + len(values)
                            target[low:high] = values
                        dirty_low = low if dirty_low is None else min(dirty_low, low)
                        dirty_high = max(dirty_high, high)
                        position += len(values)
                        if position - released >= 65536:
                            target = deck.arrays[key] = discard_pages(target, dirty=(dirty_low, dirty_high))
                            dirty_low, dirty_high, released = None, 0, position
                elif key in metadata:
                    pieces.append(piece.copy())
            finish()
        require(revision(os.fstat(fd)) == before, "SOURCE_CHANGED", "Binary source changed while reading")
        deck.files.append(
            dict(path=path, file_revision=before, sha256=sha.hexdigest(), size_bytes=os.fstat(fd).st_size)
        )
    if active_positions is not None:
        active_positions._mmap.close()


class _MappedWriter:
    """Let the strict single-property reader release dirty pages after every buffer."""

    def __init__(self, deck, keyword):
        self.deck, self.keyword = deck, keyword
        self.dtype = deck.arrays[keyword].dtype

    def __setitem__(self, selection, values):
        target = self.deck.arrays[self.keyword]
        target[selection] = values
        self.deck.arrays[self.keyword] = discard_pages(target, dirty=(selection.start, selection.stop))


def parse(source, p, work):
    deck = Interpreter(source, p["path"], work, p["file_revision"])
    if p["path"].upper().endswith(".GRID"):
        read_grid_file(deck, p["path"], p["file_revision"])
    else:
        read_file(deck, p["path"], p["file_revision"], geometry=True)
    require(deck.shape is not None, "INVALID_FORMAT", "Missing GRIDHEAD")
    for entry in p.get("property_files", []):
        if entry["format"] == "init":
            read_file(deck, entry["path"], entry["file_revision"])
        else:
            from opensubsurface.adapters.grdecl_properties import fill

            key = entry["keyword"]
            require(key not in deck.arrays, "INVALID_ARGUMENTS", f"Duplicate property {key}")
            sha = hashlib.sha256()
            with opened_source(source, entry["path"]) as (fd, _):
                require(
                    revision(os.fstat(fd)) == entry["file_revision"], "SOURCE_CHANGED", "Property changed"
                )
                target = deck.array(key)
                fill(fd, _MappedWriter(deck, key), key, len(target), 65536, sha)
                deck.arrays[key] = discard_pages(deck.arrays[key], readonly=True, dirty=(0, 0))
                require(
                    revision(os.fstat(fd)) == entry["file_revision"], "SOURCE_CHANGED", "Property changed"
                )
                deck.files.append(
                    dict(
                        path=entry["path"],
                        file_revision=entry["file_revision"],
                        sha256=sha.hexdigest(),
                        size_bytes=os.fstat(fd).st_size,
                    )
                )
    return deck


def _text(value):
    return value.decode("ascii", "replace").strip() if isinstance(value, bytes) else str(value).strip()


def read_grid_file(deck, path, expected):
    """Legacy unformatted ECLIPSE .GRID (COORDS/CORNERS per cell), as written by the simulator.

    The simulator's own geometry includes ADDZCORN/fault edits and its MINPV/PINCH activity flag.
    Corners are converted to COORD/ZCORN and must reproduce every corner on reconstruction, or
    the import is refused: no silent re-gridding.
    """
    from opensubsurface.adapters.eclipse_import import reconstruct

    pending, corners_local, flags = None, None, None
    top = bottom = None
    seen = 0
    with opened_source(deck.source, path) as (fd, _):
        before = revision(os.fstat(fd))
        require(before == expected, "SOURCE_CHANGED", "GRID source changed")
        sha = hashlib.sha256()
        with os.fdopen(os.dup(fd), "rb") as raw:
            for name, count, dtype, piece in records(_HashedStream(raw, sha)):
                if piece is None:
                    key, values = name, []
                    require(name not in {"LGR", "LGRILG", "ENDLGR"}, "UNSUPPORTED_PROFILE", "GRID with LGRs")
                    continue
                values.append(piece)
                if sum(len(v) for v in values) < count:
                    continue
                data = np.concatenate(values)
                if key == "DIMENS":
                    deck.shape = tuple(int(v) for v in data[:3])
                    require(
                        all(0 < n <= 1_000_000 for n in deck.shape) and math.prod(deck.shape) <= 500_000_000,
                        "GRID_MAPPING_ERROR",
                        "Invalid GRID dimensions",
                    )
                    nx, ny, nz = deck.shape
                    cells = math.prod(deck.shape)
                    disk_check(deck.out, cells * 1024)
                    zcorn = deck.array("ZCORN")
                    actnum = deck.array("ACTNUM")
                    corners_local = np.memmap(
                        deck.out / "grid-corners.bin", mode="w+", dtype="f4", shape=(cells, 8, 3)
                    )
                    flags = np.zeros(cells, dtype=bool)
                    top = np.full(((nx + 1) * (ny + 1), 3), np.nan)
                    bottom = np.full(((nx + 1) * (ny + 1), 3), np.nan)
                elif key == "MAPAXES":
                    deck.mapaxes = [float(v) for v in data]
                elif key in ("GRIDUNIT", "MAPUNITS"):
                    deck.suggestions.append(dict(parameter=key, tokens=[_text(v) for v in data]))
                    if key == "GRIDUNIT":
                        unit = _text(data[0]).upper()
                        deck.unit = (
                            "METRIC"
                            if unit.startswith("MET")
                            else "FIELD"
                            if unit.startswith("FEE")
                            else None
                        )
                elif key == "RADIAL":
                    require(
                        _text(data[0]).upper() == "FALSE", "UNSUPPORTED_PROFILE", "Radial GRID unsupported"
                    )
                elif key == "COORDS":
                    require(deck.shape is not None, "INVALID_FORMAT", "COORDS before DIMENS")
                    pending = data
                elif key == "CORNERS":
                    require(
                        pending is not None and len(data) == 24, "INVALID_FORMAT", "CORNERS without COORDS"
                    )
                    i, j, k = (int(v) - 1 for v in pending[:3])
                    cell = (k * ny + j) * nx + i
                    require(
                        0 <= i < nx and 0 <= j < ny and 0 <= k < nz,
                        "GRID_MAPPING_ERROR",
                        "COORDS out of range",
                    )
                    xyz = np.asarray(data, dtype=np.float64).reshape(8, 3)
                    corners_local[cell] = xyz
                    flags[cell] = int(pending[4]) != 0
                    for c in range(8):
                        di, dj, dk = c % 2, (c // 2) % 2, c // 4
                        zcorn[((2 * k + dk) * 2 * ny + (2 * j + dj)) * 2 * nx + 2 * i + di] = xyz[c, 2]
                        pillar = (j + dj) * (nx + 1) + i + di
                        if k == 0 and dk == 0:
                            top[pillar] = xyz[c]
                        if k == nz - 1 and dk == 1:
                            bottom[pillar] = xyz[c]
                    seen += 1
                    pending = None
                elif key in ("NNCHEAD", "NNC1", "NNC2", "GDORIENT"):
                    pass
                else:
                    deck.unsupported.append(
                        dict(keyword=key, section="GRID", file=path, reason="Not applied")
                    )
        require(revision(os.fstat(fd)) == before, "SOURCE_CHANGED", "GRID source changed while reading")
        deck.files.append(
            dict(path=path, file_revision=before, sha256=sha.hexdigest(), size_bytes=os.fstat(fd).st_size)
        )
    require(deck.shape is not None and seen == math.prod(deck.shape), "INVALID_FORMAT", "GRID lacks cells")
    require(
        np.isfinite(top).all() and np.isfinite(bottom).all(), "INVALID_GEOMETRY", "Pillar without corners"
    )
    coord = deck.array("COORD")
    coord[:] = np.hstack((top, bottom)).ravel()
    actnum[:] = flags
    worst = 0.0
    for start in range(0, seen, 16384):
        end = min(seen, start + 16384)
        rebuilt = reconstruct(coord, zcorn, deck.shape, start, end, 1.0, "up")
        worst = max(worst, float(np.max(np.abs(rebuilt - corners_local[start:end]))))
    # Volumes use the stored corners directly; the pillar form is informational (float32 GRID).
    deck.grid_reconstruction = dict(
        corners="as written in the .GRID file (float32), used directly",
        pillar_form_max_corner_deviation_m=worst,
        active_cells=int(flags.sum()),
    )
    corners_local.flush()
    deck.grid_corners = np.memmap(deck.out / "grid-corners.bin", mode="r", dtype="f4", shape=(seen, 8, 3))
    for name in ("COORD", "ZCORN", "ACTNUM"):
        deck.arrays[name] = discard_pages(deck.arrays[name], dirty=(0, len(deck.arrays[name])))
