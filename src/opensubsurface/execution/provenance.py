"""Runtime identities for reproducible snapshots and conservative cache invalidation."""

import importlib.metadata
import os
import shutil
from pathlib import Path

from opensubsurface.persistence.store import digest, file_hash


def solver_identity():
    executable = shutil.which(os.environ.get("OPENSUBSURFACE_FLOW_EXECUTABLE", "flow"))
    if executable is None:
        return None
    path = Path(executable).resolve()
    return dict(path=str(path), sha256=file_hash(path))


def fingerprint():
    root = Path(__file__).resolve().parents[1]
    versions = {}
    for name in (
        "numpy",
        "scipy",
        "gempy",
        "gempy-engine",
        "gstools",
        "torch",
        "segyio",
        "resdata",
        "matplotlib",
        "xtgeo",
        "pyvista",
        "trame",
        "trame-pyvista",
        "zarr",
        "shapely",
        "openpyxl",
        "reportlab",
        "pypdf",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return dict(
        versions=versions,
        flow=solver_identity(),
        source_hash=digest(
            {str(path.relative_to(root)): file_hash(path) for path in sorted(root.rglob("*.py"))}
        ),
    )
