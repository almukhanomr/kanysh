"""Revision-bound copies from owner sources for native libraries requiring filenames."""

import hashlib
import os

from opensubsurface.adapters.local_sources import LocalSources, opened_source, revision
from opensubsurface.errors import require
from opensubsurface.platform_io import read_at


def prepare_file(service, p):
    with LocalSources(service.store).opened(p["source_id"], p["path"]) as (fd, source):
        require(revision(os.fstat(fd)) == p["file_revision"], "SOURCE_CHANGED", "Repeat source_scan")
        size = os.fstat(fd).st_size
    return dict(
        source=source,
        manifest_path=p["path"],
        manifest_revision=p["file_revision"],
        input_bytes=size,
        headers={},
    )


def copy_file(context, header, target):
    sha = hashlib.sha256()
    with opened_source(context["source"], header["path"]) as (fd, _), target.open("wb") as stream:
        require(revision(os.fstat(fd)) == header["file_revision"], "SOURCE_CHANGED", "Source changed")
        size = os.fstat(fd).st_size
        offset = 0
        while offset < size:
            raw = read_at(fd, min(4 * 1024**2, size - offset), offset)
            require(bool(raw), "SOURCE_CHANGED", "Source truncated during snapshot")
            stream.write(raw)
            sha.update(raw)
            offset += len(raw)
        require(revision(os.fstat(fd)) == header["file_revision"], "SOURCE_CHANGED", "Source changed")
    return sha.hexdigest()
