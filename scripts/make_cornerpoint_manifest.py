"""Owner helper: declare a native grid and six properties without loading its geometry.

Run on the import host, including inside WSL2 for Windows sources. Constants are explicit assumptions.
"""

import argparse
import json
from pathlib import Path

from opensubsurface.adapters.cornerpoint import FORMAT, Manifest
from opensubsurface.adapters.large_grid import UNITS
from opensubsurface.adapters.local_sources import opened_source, parts, path_revision, revision


def main(a):
    root = a.directory.resolve()
    info = root.stat()
    source = dict(root=str(root), device=info.st_dev, inode=info.st_ino)

    def declaration(path):
        parts(path)
        with opened_source(source, path) as (fd, _):
            import os

            return dict(path=path, file_revision=revision(os.fstat(fd)))

    properties = {}
    for entry in a.constant:
        name, value = entry.split("=", 1)
        if name in properties:
            raise SystemExit("Duplicate property " + name)
        properties[name] = dict(constant=float(value))
    for entry in a.property:
        name, value = entry.split("=", 1)
        path, keyword = value.rsplit(":", 1)
        if name in properties:
            raise SystemExit("Duplicate property " + name)
        properties[name] = dict(declaration(path), keyword=keyword)
    manifest = Manifest.model_validate(
        dict(
            format=FORMAT,
            shape=a.shape,
            geometry=dict(declaration(a.geometry), format=a.format),
            crs=a.crs,
            vertical_datum=a.datum,
            length_unit=a.length_unit,
            z_direction=a.z_direction,
            units=UNITS,
            arrays=properties,
            assumptions=a.assumption,
        )
    )
    parts(a.filename)
    path = root / a.filename
    # Never overwrite an existing user manifest or symlink.
    with path.open("x") as stream:
        stream.write(manifest.model_dump_json(indent=2) + "\n")
    print(json.dumps(dict(path=str(path), file_revision=path_revision(path)), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--geometry", required=True, help="Relative path inside directory")
    parser.add_argument("--format", choices=["grdecl", "egrid", "roff"], required=True)
    parser.add_argument("--shape", type=int, nargs=3, required=True)
    parser.add_argument("--crs", required=True)
    parser.add_argument("--datum", required=True)
    parser.add_argument("--length-unit", choices=["m", "ft"], required=True)
    parser.add_argument("--z-direction", choices=["up", "down"], required=True)
    parser.add_argument("--constant", action="append", default=[], help="field=value")
    parser.add_argument("--property", action="append", default=[], help="field=relative/path:KEYWORD")
    parser.add_argument("--assumption", action="append", required=True)
    parser.add_argument("--filename", default="cornerpoint.json")
    main(parser.parse_args())
