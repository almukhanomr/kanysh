"""Bounded static ECLIPSE interpreter; source positions and unsupported syntax are evidence.

No simulator initialization, saturation equilibrium, MINPV/pinch or fault transmissibility
application is claimed. Numeric arrays are disk-backed in ECLIPSE I-fast order.
"""

import hashlib
import math
import os
import re
import shutil
from pathlib import PurePosixPath

import numpy as np

from opensubsurface.adapters.local_sources import opened_source, parts, revision
from opensubsurface.errors import require

SECTIONS = {"RUNSPEC", "GRID", "EDIT", "PROPS", "REGIONS", "SOLUTION", "SUMMARY", "SCHEDULE"}
STATIC = {"GRID", "EDIT", "PROPS", "REGIONS"}
ARRAYS = {
    "COORD",
    "ZCORN",
    "ACTNUM",
    "PORO",
    "NTG",
    "PERMX",
    "PERMY",
    "PERMZ",
    "SWAT",
    "FIPNUM",
    "SATNUM",
    "EQLNUM",
    "PVTNUM",
}
EDITS = {"EQUALS", "MULTIPLY", "COPY", "ADD"}
SINGLES = {"DIMENS", "SPECGRID", "BOX", "MAPAXES", "MAPUNITS", "GRIDUNIT"}
FLAGS = SECTIONS | {"METRIC", "FIELD", "LAB", "ENDBOX", "END", "NOECHO", "ECHO"}
LEX = re.compile(r"'(?:[^']|'')*'|/|[^\s,/]+")


def discard_pages(array):
    """Remap a flushed array to bound RSS on both Linux and macOS.

    MADV_DONTNEED alone retains resident file pages on macOS. Callers must replace
    their array handle with the returned mapping and retain no old slice views.
    """
    filename, dtype, shape = array.filename, array.dtype, array.shape
    array.flush()
    array._mmap.close()
    return np.memmap(filename, dtype=dtype, shape=shape, mode="r+")


def relative_include(parent, value):
    require("\\" not in value and "\x00" not in value, "INVALID_SOURCE_PATH", "Invalid INCLUDE path")
    path = PurePosixPath(value)
    require(not path.is_absolute(), "INVALID_SOURCE_PATH", "INCLUDE must be relative")
    stack = list(PurePosixPath(parent).parent.parts)
    for part in path.parts:
        if part == "..":
            require(bool(stack), "INVALID_SOURCE_PATH", "INCLUDE escapes registered source")
            stack.pop()
        elif part != ".":
            require(not part.startswith("."), "INVALID_SOURCE_PATH", "Hidden INCLUDE path forbidden")
            stack.append(part)
    result = str(PurePosixPath(*stack))
    parts(result)
    return result


def events(source, path, evidence, expected=None, stack=(), root=None, control=None):
    """Stream line/token events and expand INCLUDE without loading whole property records."""
    require(path not in stack and len(stack) < 32, "INVALID_FORMAT", "Cyclic/deep INCLUDE")
    root = path if root is None else root
    control = {} if control is None else control
    with opened_source(source, path) as (fd, _):
        before = revision(os.fstat(fd))
        require(expected in (None, before), "SOURCE_CHANGED", "Deck input changed")
        sha = hashlib.sha256()
        keyword, ended = None, False
        include = []
        with os.fdopen(os.dup(fd), "rb") as stream:
            for line_no, raw in enumerate(stream, 1):
                require(len(raw) <= 1024 * 1024, "INVALID_FORMAT", "Deck line exceeds 1 MiB")
                sha.update(raw)
                if ended or control.get("end"):
                    continue
                text = re.split(r"--(?=(?:[^']*'[^']*')*[^']*$)", raw.decode("latin-1"), maxsplit=1)[
                    0
                ].strip()
                if not text:
                    continue
                location = dict(file=path, line=line_no)
                # Keywords in published decks occupy a line of their own. Inline supported
                # keywords are also accepted except inside a multi-record edit block.
                tokens = LEX.findall(text)
                first = tokens[0].upper()
                is_header = bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,15}", text))
                is_header |= keyword not in EDITS and first in ARRAYS | EDITS | FLAGS | SINGLES | {"INCLUDE"}
                if is_header:
                    keyword = first
                    if keyword == "ENDINC":
                        ended = True
                        continue
                    if keyword == "END":
                        control["end"] = True
                    if keyword != "INCLUDE":
                        yield "keyword", keyword, location
                    tokens = tokens[1:]
                if keyword == "INCLUDE":
                    for token in tokens:
                        if token == "/":
                            require(
                                len(include) == 1, "INVALID_FORMAT", "One quoted INCLUDE filename required"
                            )
                            target = relative_include(root, include[0])
                            yield "include", target, location
                            yield from events(
                                source, target, evidence, stack=(*stack, path), root=root, control=control
                            )
                            include = []
                            keyword = None
                            break  # Text after slash is a deck comment.
                        include.append(token.strip("'").replace("''", "'"))
                    continue
                if tokens:
                    for token in tokens:
                        yield "token", token, location
                        if token == "/":
                            # ECLIPSE permits free-form commentary after the record slash.
                            break
        require(not include, "INVALID_FORMAT", "Unterminated INCLUDE")
        require(revision(os.fstat(fd)) == before, "SOURCE_CHANGED", "Deck changed while reading")
        evidence.append(
            dict(path=path, file_revision=before, sha256=sha.hexdigest(), size_bytes=os.fstat(fd).st_size)
        )


def expanded(tokens, defaults):
    """Small metadata/edit records only; numeric arrays use the bounded writer below."""
    result = []
    for token in tokens:
        if "*" in token:
            count, value = token.split("*", 1)
            count = int(count or 1)
            require(count <= 1000, "INVALID_FORMAT", "Metadata repeat too large")
            result.extend([value or None] * count)
        else:
            result.append(token.strip("'"))
    require(len(result) <= len(defaults), "INVALID_FORMAT", "Too many record items")
    return [defaults[i] if i >= len(result) or result[i] is None else result[i] for i in range(len(defaults))]


class BoxSlices:
    """Constant-memory random access to contiguous I rows in an ECLIPSE BOX."""

    def __init__(self, shape, box):
        self.nx, self.ny, _ = shape
        self.i1, self.i2, self.j1, self.j2, self.k1, self.k2 = box
        self.rows = self.j2 - self.j1 + 1
        self.cells = (self.i2 - self.i1 + 1) * self.rows * (self.k2 - self.k1 + 1)

    def __len__(self):
        return self.rows * (self.k2 - self.k1 + 1)

    def __getitem__(self, index):
        if not 0 <= index < len(self):
            raise IndexError(index)
        k = self.k1 - 1 + index // self.rows
        j = self.j1 - 1 + index % self.rows
        return slice((k * self.ny + j) * self.nx + self.i1 - 1, (k * self.ny + j) * self.nx + self.i2)


class Interpreter:
    def __init__(self, source, path, out, file_revision=None):
        self.source, self.path, self.out, self.expected = source, path, out, file_revision
        self.shape, self.unit, self.mapaxes = None, None, None
        self.arrays, self.files, self.unsupported, self.suggestions = {}, [], [], []
        self.applied, self.section, self.box = [], "RUNSPEC", None

    def array(self, name):
        require(self.shape is not None, "INVALID_FORMAT", "DIMENS/SPECGRID required before arrays")
        if name not in self.arrays:
            size = (
                (self.shape[0] + 1) * (self.shape[1] + 1) * 6
                if name == "COORD"
                else math.prod(self.shape) * (8 if name == "ZCORN" else 1)
            )
            require(
                size * 8 < shutil.disk_usage(self.out).free * 0.9,
                "INSUFFICIENT_DISK",
                "Not enough disk for bounded deck array " + name,
            )
            path = self.out / (name + ".bin")
            # Initialize with a bounded write buffer, never touch an entire large mmap.
            buffer = np.full(65536, np.nan).tobytes()
            with path.open("wb") as stream:
                for start in range(0, size, 65536):
                    stream.write(buffer[: min(65536, size - start) * 8])
            self.arrays[name] = np.memmap(path, dtype="f8", mode="r+", shape=(size,))
        return self.arrays[name]

    def issue(self, keyword, loc, reason):
        self.unsupported.append(dict(keyword=keyword, section=self.section, reason=reason, **loc))

    def bounds(self, values, base):
        values = expanded(values, list(base))
        answer = tuple(int(v) for v in values)
        require(
            all(1 <= answer[2 * d] <= answer[2 * d + 1] <= self.shape[d] for d in range(3)),
            "GRID_MAPPING_ERROR",
            "BOX outside grid",
        )
        return answer

    def whole(self):
        return (1, self.shape[0], 1, self.shape[1], 1, self.shape[2])

    def slices(self, box):
        nx, ny, _ = self.shape
        i1, i2, j1, j2, k1, k2 = box
        for k in range(k1 - 1, k2):
            for j in range(j1 - 1, j2):
                yield slice((k * ny + j) * nx + i1 - 1, (k * ny + j) * nx + i2)

    def edit(self, keyword, record, loc, edit_box):
        require(len(record) >= 2, "INVALID_FORMAT", "Edit requires property and operand")
        name, operand = (v.strip("'").upper() for v in record[:2])
        target_name = operand if keyword == "COPY" else name
        if (
            name not in ARRAYS
            or target_name not in ARRAYS
            or name in {"COORD", "ZCORN"}
            or target_name in {"COORD", "ZCORN"}
        ):
            self.issue(keyword + ":" + name, loc, "Unsupported edited array")
            return edit_box
        box = self.bounds(record[2:], edit_box)
        target = self.array(target_name)
        if keyword == "COPY":
            require(name in self.arrays, "MISSING_PROPERTY", "COPY source undefined: " + name)
            value = self.arrays[name]
        else:
            value = float(operand.replace("D", "E"))
            require(np.isfinite(value), "INVALID_FORMAT", "Nonfinite edit value")
        for selection in self.slices(box):
            if keyword == "COPY":
                target[selection] = value[selection]
            elif keyword == "EQUALS":
                target[selection] = value
            elif keyword == "ADD":
                target[selection] += value
            else:
                target[selection] *= value
        self.arrays[target_name] = discard_pages(target)
        if keyword == "COPY" and name != target_name:
            self.arrays[name] = discard_pages(self.arrays[name])
        self.applied.append(dict(keyword=keyword, property=target_name, box=box, **loc))
        return box

    def parse(self):
        keyword, record, location, edit_box = None, [], {}, None
        position = 0
        target = None
        selections = None
        selection_index, selection_offset = 0, 0
        terminated = True
        for kind, value, loc in events(self.source, self.path, self.files, self.expected):
            if kind == "include":
                continue
            if kind == "keyword":
                require(terminated or target is None, "INVALID_FORMAT", "Unterminated array " + str(keyword))
                keyword, record, location, target = value, [], loc, None
                terminated, position = False, 0
                if keyword in SECTIONS:
                    self.section, self.box = keyword, None
                if keyword in {"METRIC", "FIELD", "LAB"}:
                    require(self.unit in (None, keyword), "INVALID_UNITS", "Conflicting unit declarations")
                    self.unit = keyword
                if keyword == "ENDBOX":
                    self.box = None
                if keyword in ARRAYS and self.section in STATIC:
                    target = self.array(keyword)
                    selections = (
                        BoxSlices(self.shape, self.box)
                        if self.box and keyword not in {"COORD", "ZCORN"}
                        else None
                    )
                    selection_index, selection_offset = 0, 0
                elif keyword in EDITS and self.shape:
                    edit_box = self.box or self.whole()
                elif keyword not in FLAGS | SINGLES | EDITS:
                    self.issue(
                        keyword,
                        loc,
                        "Outside static scope"
                        if self.section not in STATIC
                        else "Not implemented; not applied",
                    )
                continue
            if target is not None:
                if value == "/":
                    count = selections.cells if selections else len(target)
                    require(
                        position == count,
                        "GRID_MAPPING_ERROR",
                        f"{keyword}: {position} values, expected {count}",
                    )
                    target = self.arrays[keyword] = discard_pages(target)
                    terminated = True
                    continue
                require(not terminated, "INVALID_FORMAT", "Trailing array data")
                run, number = value.split("*", 1) if "*" in value else ("1", value)
                require(
                    bool(number), "UNSUPPORTED_DEFAULT", "Implicit property defaults need explicit values"
                )
                count, number = int(run), float(number.replace("D", "E").replace("d", "e"))
                limit = selections.cells if selections else len(target)
                require(
                    0 < count <= limit - position and np.isfinite(number),
                    "GRID_MAPPING_ERROR",
                    "Array run/count invalid",
                )
                while count:
                    if selections:
                        s = selections[selection_index]
                        start = s.start + selection_offset
                        take = min(count, s.stop - start, 65536)
                    else:
                        start, take = position, min(count, 65536)
                    target[start : start + take] = number
                    count, position = count - take, position + take
                    if selections:
                        selection_offset += take
                        if s.start + selection_offset == s.stop:
                            selection_index, selection_offset = selection_index + 1, 0
                    if position % 65536 == 0:
                        target = self.arrays[keyword] = discard_pages(target)
                continue
            if value != "/":
                # Unknown/PVT/dynamic records are never accumulated into unbounded lists.
                if keyword in SINGLES | EDITS:
                    record.append(value)
                    require(len(record) < 128, "INVALID_FORMAT", "Metadata record too long")
                continue
            if keyword in {"DIMENS", "SPECGRID"}:
                dims = tuple(int(v) for v in record[:3])
                require(
                    len(dims) == 3
                    and all(0 < n <= 1_000_000 for n in dims)
                    and math.prod(dims) <= 500_000_000,
                    "GRID_MAPPING_ERROR",
                    "Invalid dimensions",
                )
                require(self.shape in (None, dims), "GRID_MAPPING_ERROR", "Conflicting dimensions")
                self.shape = dims
            elif keyword == "BOX":
                self.box = self.bounds(record, self.whole())
            elif keyword == "MAPAXES":
                self.mapaxes = [float(v) for v in record]
                require(len(self.mapaxes) == 6, "INVALID_FORMAT", "MAPAXES requires six numbers")
            elif keyword in {"GRIDUNIT", "MAPUNITS"}:
                self.suggestions.append(
                    dict(parameter=keyword, tokens=record.copy(), **location, requires_user_confirmation=True)
                )
            elif keyword in EDITS and record and self.section in STATIC:
                edit_box = self.edit(keyword, record, location, edit_box)
            record = []
        require(target is None or terminated, "INVALID_FORMAT", "Unterminated final array")
        require(self.shape is not None, "INVALID_FORMAT", "Grid dimensions missing")
        for name, array in list(self.arrays.items()):
            self.arrays[name] = discard_pages(array)
        return self
