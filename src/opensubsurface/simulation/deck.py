"""Snapshot of the user's deck and its INCLUDE closure from an owner-registered source.

The simulator only ever sees this copy. Nothing is generated or rewritten: files are copied
byte-for-byte with revision checks. Keywords that would read files outside the closure are
refused, so the simulator cannot be pointed at arbitrary paths by deck text.
"""

import hashlib
import os
import re
from pathlib import Path, PurePosixPath

from opensubsurface.adapters.eclipse_deck import relative_include
from opensubsurface.adapters.local_sources import opened_source, revision
from opensubsurface.errors import require
from opensubsurface.platform_io import read_at

# Keywords whose arguments name external files; not supported in this profile.
EXTERNAL = {
    "GDFILE",
    "IMPORT",
    "PATHS",
    "RESTART",
    "LOAD",
    "SAVE",
    "USECUPL",
    "DUMPCUPL",
    "GETGLOB",
    "SKIPREST",
}
MAX_FILES, MAX_BYTES = 2000, 4 * 1024**3


def _keywords(text):
    """(line number, keyword, following text) for keyword lines, comments removed."""
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        line = raw.split("--", 1)[0].strip()
        match = re.match(r"^([A-Z][A-Z0-9_]{0,7})\s*$", line)
        if match:
            yield index + 1, match[1], lines[index + 1 : index + 6]


def _include_target(following):
    for raw in following:
        text = raw.split("--", 1)[0].strip()
        if not text:
            continue
        match = re.match(r"^'([^']+)'\s*/?|^\"([^\"]+)\"\s*/?|^(\S+?)\s*/", text)
        require(match is not None, "INVALID_FORMAT", "INCLUDE requires one file name")
        return next(group for group in match.groups() if group)
    require(False, "INVALID_FORMAT", "Unterminated INCLUDE")


def closure(source, path, expected_revision):
    """Resolve the INCLUDE tree without reading data blocks beyond keyword scanning."""
    files, pending, seen = [], [(path, expected_revision)], set()
    total = 0
    while pending:
        current, wanted = pending.pop(0)
        if current in seen:
            continue
        seen.add(current)
        require(len(seen) <= MAX_FILES, "DECK_TOO_LARGE", "More than 2000 INCLUDE files")
        with opened_source(source, current) as (fd, _):
            info = os.fstat(fd)
            current_revision = revision(info)
            require(
                wanted is None or current_revision == wanted,
                "SOURCE_CHANGED",
                f"{current} changed since discovery; repeat folder_assess/source_scan",
                "file_revision",
            )
            total += info.st_size
            require(total <= MAX_BYTES, "DECK_TOO_LARGE", "Deck closure exceeds 4 GiB")
            text = _read(fd, info.st_size).decode("latin-1")
        files.append(dict(path=current, file_revision=current_revision, size_bytes=info.st_size))
        for line, keyword, following in _keywords(text):
            require(
                keyword not in EXTERNAL,
                "UNSUPPORTED_DECK",
                f"{current}:{line}: {keyword} references files outside the INCLUDE closure",
                "path",
                "Run a deck without RESTART/IMPORT/GDFILE/PATHS (or flatten them into INCLUDE files).",
            )
            if keyword == "INCLUDE":
                # ECLIPSE/OPM resolve INCLUDE relative to the main DATA file, as eclipse_import does.
                target = relative_include(path, _include_target(following))
                pending.append((str(PurePosixPath(target)), None))
    return files


def _read(fd, size):
    chunks, offset = [], 0
    while offset < size:
        raw = read_at(fd, min(16 * 1024**2, size - offset), offset)
        require(bool(raw), "SOURCE_CHANGED", "Deck file truncated while reading")
        chunks.append(raw)
        offset += len(raw)
    return b"".join(chunks)


def snapshot(source, files, target):
    """Copy every closure file to target/<relative path>; return sha256 per path."""
    hashes = {}
    root = Path(target)
    for entry in files:
        destination = root.joinpath(*PurePosixPath(entry["path"]).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256()
        with opened_source(source, entry["path"]) as (fd, _), destination.open("wb") as stream:
            require(
                revision(os.fstat(fd)) == entry["file_revision"], "SOURCE_CHANGED", entry["path"] + " changed"
            )
            offset, size = 0, os.fstat(fd).st_size
            while offset < size:
                raw = read_at(fd, min(16 * 1024**2, size - offset), offset)
                require(bool(raw), "SOURCE_CHANGED", entry["path"] + " truncated")
                stream.write(raw)
                sha.update(raw)
                offset += len(raw)
            require(
                revision(os.fstat(fd)) == entry["file_revision"], "SOURCE_CHANGED", entry["path"] + " changed"
            )
        hashes[entry["path"]] = sha.hexdigest()
    return hashes
