"""Create a header-only manifest for seven existing NPY files; run on the import host (WSL)."""

import argparse
import json
import os
from pathlib import Path

from opensubsurface.adapters.grdecl_properties import FORMAT as GRDECL_FORMAT
from opensubsurface.adapters.large_grid import FIELDS, FORMAT, UNITS, Manifest, read_header
from opensubsurface.adapters.local_sources import path_revision, revision


def main(args):
    arrays = {}
    constants = dict(item.split("=", 1) for item in args.constant)
    if set(constants) - set(FIELDS):
        raise SystemExit("Unknown constant field")
    keywords = dict(
        active="ACTNUM",
        zones="FIPNUM",
        phi="PORO",
        ntg="NTG",
        sw="SWAT",
        permeability_md="PERMX",
        kz_ratio="PERMZ",
    )
    for name in FIELDS:
        if name in constants:
            arrays[name] = dict(constant=float(constants[name]))
            continue
        path = args.directory / ((keywords[name] + ".grdecl") if args.format == "grdecl" else name + ".npy")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            initial = os.fstat(fd)
            if args.format == "npy":
                read_header(fd, args.shape, name)
            if revision(os.fstat(fd)) != revision(initial):
                raise SystemExit("File changed: " + name)
            arrays[name] = dict(path=path.name, file_revision=revision(initial))
            if args.format == "grdecl":
                arrays[name]["keyword"] = keywords[name]
        finally:
            os.close(fd)
    manifest = Manifest.model_validate(
        dict(
            format=GRDECL_FORMAT if args.format == "grdecl" else FORMAT,
            grid=dict(shape=args.shape, extent=args.extent),
            cartesian_basis=args.cartesian_basis,
            crs=args.crs,
            vertical_datum=args.datum,
            z_direction="up",
            units=UNITS,
            arrays=arrays,
        )
    )
    output = args.directory / args.filename
    if output.exists():
        raise SystemExit("Manifest already exists; use another --filename")
    output.write_text(manifest.model_dump_json(indent=2) + "\n")
    print(json.dumps(dict(path=str(output.resolve()), file_revision=path_revision(output)), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--shape", type=int, nargs=3, required=True)
    parser.add_argument("--extent", type=float, nargs=6, required=True)
    parser.add_argument("--crs", required=True)
    parser.add_argument("--datum", required=True)
    parser.add_argument("--format", choices=["npy", "grdecl"], default="npy")
    parser.add_argument(
        "--cartesian-basis", help="Required for GRDECL: why uniform Cartesian geometry is valid"
    )
    parser.add_argument(
        "--constant",
        action="append",
        default=[],
        help="Explicit field=value for absent GRDECL field; repeatable",
    )
    parser.add_argument(
        "--filename", default="model.json", choices=["model.json", "model-v2.json", "model-v3.json"]
    )
    main(parser.parse_args())
