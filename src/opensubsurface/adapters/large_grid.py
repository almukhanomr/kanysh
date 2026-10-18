"""Bounded Cartesian property storage. Flattened C order: k/Z is fastest, Z increases upward.

External paths are opened through registered directory descriptors, never np.load(path).
NPY object arrays, Fortran layout, symlinks, changing files and implicit units are rejected.
"""

import hashlib
import json
import math
import os
import shutil
from contextlib import contextmanager
from pathlib import PurePosixPath

import numpy as np
import zarr
from numcodecs import Blosc
from pydantic import Field, model_validator

from opensubsurface.adapters.grdecl_properties import FORMAT as GRDECL_FORMAT
from opensubsurface.adapters.grdecl_properties import KEYWORDS
from opensubsurface.adapters.local_sources import LocalSources, opened_source, parts, revision
from opensubsurface.domain.numerics import PROPERTY_BOUNDS
from opensubsurface.errors import require
from opensubsurface.persistence.store import digest
from opensubsurface.platform_io import read_at
from opensubsurface.schemas import LargeGrid, Strict

FORMAT = "opensubsurface.cartesian.npy.v1"
STORAGE = "cartesian-zarr-flat-v1"
FIELDS = ("active", "zones", "phi", "ntg", "sw", "permeability_md", "kz_ratio")
UNITS = dict(
    active="boolean",
    zones="zone_id",
    phi="fraction",
    ntg="fraction",
    sw="fraction",
    permeability_md="mD",
    kz_ratio="fraction",
)
BOUNDS = dict(PROPERTY_BOUNDS, kz_ratio=(0, 1))


class ArrayFile(Strict):
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    file_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    keyword: str | None = None
    constant: float | None = None

    @model_validator(mode="after")
    def source_or_constant(self):
        if self.constant is None:
            if self.path is None or self.file_revision is None:
                raise ValueError("File path and revision required")
        elif any(v is not None for v in (self.path, self.file_revision, self.keyword)):
            raise ValueError("Choose explicit constant or source file")
        return self


class Manifest(Strict):
    format: str
    grid: LargeGrid
    crs: str
    vertical_datum: str
    z_direction: str
    units: dict[str, str]
    arrays: dict[str, ArrayFile]
    cartesian_basis: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def supported(self):
        if self.format not in (FORMAT, GRDECL_FORMAT) or self.z_direction != "up" or self.units != UNITS:
            raise ValueError("Explicit Cartesian format, Z up and declared canonical units required")
        paths = [a.path for a in self.arrays.values() if a.path is not None]
        if set(self.arrays) != set(FIELDS) or len(set(paths)) != len(paths):
            raise ValueError("Seven property declarations; distinct files required")
        if self.format == FORMAT:
            if any(a.constant is not None or a.keyword is not None for a in self.arrays.values()):
                raise ValueError("NPY profile requires all seven files; no GRDECL keywords/constants")
        else:
            if not self.cartesian_basis or not self.cartesian_basis.strip():
                raise ValueError(
                    "GRDECL properties require explicit basis for uniform Cartesian geometry; no COORD/ZCORN"
                )
            for name, entry in self.arrays.items():
                if entry.constant is None and entry.keyword not in KEYWORDS[name]:
                    raise ValueError("Unsupported property keyword: " + name)
        return self


def read_header(fd, shape, name):
    with os.fdopen(os.dup(fd), "rb") as stream:
        stream.seek(0)
        version = np.lib.format.read_magic(stream)
        require(version in ((1, 0), (2, 0)), "UNSUPPORTED_FORMAT", "NPY v1/v2 required")
        reader = (
            np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
        )
        dimensions, fortran, dtype = reader(stream, max_header_size=16384)
        offset = stream.tell()
    cells = math.prod(shape)
    require(
        not fortran and tuple(dimensions) in (tuple(shape), (cells,)),
        "GRID_MAPPING_ERROR",
        "NPY must have declared shape or flat C layout",
    )
    allowed = dtype.kind in ("b", "u", "i") if name in ("active", "zones") else dtype.kind == "f"
    require(
        allowed and dtype.itemsize <= 8 and not dtype.hasobject,
        "UNSUPPORTED_FORMAT",
        "Only numeric arrays; no pickle/object or structured dtype",
    )
    require(
        os.fstat(fd).st_size == offset + cells * dtype.itemsize,
        "INVALID_FORMAT",
        "NPY length/header mismatch or trailing bytes",
    )
    return dtype, offset


def prepare(service, p):
    sources = LocalSources(service.store)
    with sources.opened(p["source_id"], p["path"]) as (fd, source):
        require(revision(os.fstat(fd)) == p["file_revision"], "SOURCE_CHANGED", "Repeat source_scan")
        require(os.fstat(fd).st_size <= 65536, "MANIFEST_TOO_LARGE", "Manifest limit 64 KiB")
        raw = read_at(fd, 65537, 0)
        if json.loads(raw).get("format") == "opensubsurface.cornerpoint.xtgeo.v1":
            from opensubsurface.adapters.cornerpoint import prepare as prepare_cornerpoint

            return prepare_cornerpoint(service, p, raw, source)
        manifest = Manifest.model_validate_json(raw).model_dump(mode="json")
        require(revision(os.fstat(fd)) == p["file_revision"], "SOURCE_CHANGED", "Manifest changed")
    base = PurePosixPath(p["path"]).parent
    total, headers = 0, {}
    for name in FIELDS:
        entry = manifest["arrays"][name]
        if entry["constant"] is not None:
            headers[name] = dict(constant=entry["constant"])
            continue
        parts(entry["path"])
        path = str(base / entry["path"])
        with sources.opened(p["source_id"], path) as (fd, _):
            require(
                revision(os.fstat(fd)) == entry["file_revision"], "SOURCE_CHANGED", "NPY changed: " + name
            )
            if manifest["format"] == FORMAT:
                dtype, offset = read_header(fd, manifest["grid"]["shape"], name)
            else:
                dtype, offset = (
                    np.dtype("bool" if name == "active" else "int32" if name == "zones" else "float64"),
                    0,
                )
            headers[name] = dict(
                path=path,
                dtype=dtype.str,
                offset=offset,
                file_revision=entry["file_revision"],
                size_bytes=os.fstat(fd).st_size,
                keyword=entry["keyword"],
            )
            total += os.fstat(fd).st_size
    return dict(
        source=source,
        manifest=manifest,
        headers=headers,
        input_bytes=total,
        manifest_path=p["path"],
        manifest_revision=p["file_revision"],
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
    )


def inspect_source(service, p):
    prepared = prepare(service, p)
    return dict(
        status="INSPECTED",
        format=prepared["manifest"]["format"],
        manifest=prepared["manifest"],
        input_bytes=prepared["input_bytes"],
        cells=math.prod(prepared["manifest"].get("grid", prepared["manifest"])["shape"]),
        headers=prepared["headers"],
        scope="headers only; full QC and hashes during grid_import",
        preview_is_untrusted_data=True,
    )


def check_source(context):
    source = context["source"]
    for path, expected in [(context["manifest_path"], context["manifest_revision"])] + [
        (h["path"], h["file_revision"]) for h in context["headers"].values() if h.get("path")
    ]:
        with opened_source(source, path) as (fd, _):
            require(revision(os.fstat(fd)) == expected, "SOURCE_CHANGED", "Import input changed")


def import_grid(context, block_cells, out):
    if context["manifest"]["format"] == "opensubsurface.cornerpoint.xtgeo.v1":
        from opensubsurface.adapters.cornerpoint import import_grid as import_cornerpoint

        return import_cornerpoint(context, block_cells, out)
    manifest, headers = context["manifest"], context["headers"]
    cells = math.prod(manifest["grid"]["shape"])
    require(
        math.ceil(cells / block_cells) <= 10000,
        "BLOCK_TOO_SMALL",
        "Increase block_cells: max 10000 chunks per array bounds ZIP metadata RAM",
    )
    # Both attempt output and immutable publication can coexist. No assumed compression ratio.
    require(
        shutil.disk_usage(out).free > max(cells * 45, context["input_bytes"]) * 2.1 + 64 * 1024**2,
        "INSUFFICIENT_DISK",
        "Need space for attempt output and immutable snapshot",
    )
    check_source(context)
    hashes = {}
    with zarr.ZipStore(str(out / "grid.zip"), mode="w") as store:
        group = zarr.group(store=store)
        order = "C" if manifest["format"] == FORMAT else "ECLIPSE"
        group.attrs.update(storage=STORAGE, grid=manifest["grid"], order=order, z_direction="up")

        def create(name, dtype):
            return group.create_dataset(
                name,
                shape=(cells,),
                chunks=(min(block_cells, cells),),
                dtype=dtype,
                compressor=Blosc(cname="zstd", clevel=1, shuffle=Blosc.BITSHUFFLE),
            )

        if order == "ECLIPSE":
            from opensubsurface.adapters.grdecl_properties import import_arrays

            hashes = import_arrays(context, block_cells, group, create)
        for name in FIELDS if order == "C" else []:
            header = headers[name]
            with opened_source(context["source"], header["path"]) as (fd, _):
                require(revision(os.fstat(fd)) == header["file_revision"], "SOURCE_CHANGED", "NPY changed")
                dtype, offset = read_header(fd, manifest["grid"]["shape"], name)
                target = create(name, dtype)
                sha = hashlib.sha256(read_at(fd, offset, 0))
                for start in range(0, cells, block_cells):
                    count = min(block_cells, cells - start)
                    raw = read_at(fd, count * dtype.itemsize, offset + start * dtype.itemsize)
                    require(len(raw) == count * dtype.itemsize, "SOURCE_CHANGED", "Truncated NPY")
                    sha.update(raw)
                    target[start : start + count] = np.frombuffer(raw, dtype=dtype)
                require(revision(os.fstat(fd)) == header["file_revision"], "SOURCE_CHANGED", "NPY changed")
                hashes[name] = sha.hexdigest()
    check_source(context)
    summary = dict(
        storage=STORAGE,
        order=order,
        source_format=manifest["format"],
        cartesian_basis=manifest.get("cartesian_basis"),
        grid=manifest["grid"],
        block_cells=block_cells,
        cells=cells,
        crs=manifest["crs"],
        vertical_datum=manifest["vertical_datum"],
        z_direction="up",
        units=UNITS,
        backend="chunked-cpu",
        source_input_bytes=context["input_bytes"],
        source_sha256=hashes,
        input_declarations=manifest["arrays"],
        manifest_sha256=context["manifest_sha256"],
        working_memory_bound_bytes=block_cells * 192,
        working_memory_scope="Block buffers; runtime libraries and bounded ZIP metadata are additional",
    )
    obj = dict(summary=summary, paths={"grid.zip": str(out / "grid.zip")})
    qc = scan_properties(obj)
    summary.update(qc)
    return "properties", summary, {"grid.zip": out / "grid.zip"}


@contextmanager
def open_grid(obj):
    if obj["summary"].get("storage") == "cornerpoint-zarr-v1":
        from opensubsurface.adapters.cornerpoint import open_grid as open_cornerpoint

        with open_cornerpoint(obj) as group:
            yield group
        return
    with zarr.ZipStore(obj["paths"]["grid.zip"], mode="r") as store:
        group = zarr.open_group(store=store, mode="r")
        cells = math.prod(obj["summary"]["grid"]["shape"])
        require(
            group.attrs["storage"] == STORAGE
            and group.attrs["order"] == obj["summary"].get("order", "C")
            and group.attrs["order"] in ("C", "ECLIPSE")
            and group.attrs["z_direction"] == "up"
            and group.attrs["grid"] == obj["summary"]["grid"],
            "GRID_MAPPING_ERROR",
            "Stored grid metadata mismatch",
        )
        require(set(group.array_keys()) == set(FIELDS), "INVALID_FORMAT", "Missing/extra grid arrays")
        for name in FIELDS:
            a = group[name]
            require(
                a.shape == (cells,)
                and len(a.chunks) == 1
                and 1 <= a.chunks[0] <= 1048576
                and a.dtype.kind in ("bui" if name in ("active", "zones") else "f")
                and a.dtype.itemsize <= 8,
                "INVALID_FORMAT",
                "Invalid stored array metadata",
            )
            expected = (cells + a.chunks[0] - 1) // a.chunks[0]
            # Missing Zarr chunks otherwise read as fill values, potentially a plausible false result.
            actual = [
                key
                for key in store.keys()
                if key.startswith(name + "/") and not key.split("/")[-1].startswith(".")
            ]
            require(
                len(actual) == expected and all(f"{name}/{i}" in store for i in range(expected)),
                "INTEGRITY_ERROR",
                "Missing/extra Zarr chunks",
            )
        yield group


def blocks(group):
    if group.attrs["storage"] == "cornerpoint-zarr-v1":
        from opensubsurface.adapters.cornerpoint import blocks as cornerpoint_blocks

        yield from cornerpoint_blocks(group)
        return
    count = group["active"].shape[0]
    step = min(a.chunks[0] for _, a in group.arrays())
    arrays = {name: group[name] for name in FIELDS}
    for start in range(0, count, step):
        yield (
            start,
            {name: np.asarray(array[start : min(count, start + step)]) for name, array in arrays.items()},
        )


def qc_block(data):
    require(np.all((data["active"] == 0) | (data["active"] == 1)), "QC_FAILED", "ACTNUM must be 0/1")
    active = data["active"].astype(bool)
    require(np.all(data["zones"][active] >= 1), "QC_FAILED", "Active zones must be positive integers")
    for name, (low, high) in BOUNDS.items():
        v = data[name][active]
        require(np.all(np.isfinite(v) & (v >= low) & (v <= high)), "QC_FAILED", name + " out of bounds")
        if name == "kz_ratio":
            require(np.all(v > 0), "QC_FAILED", "kz_ratio must be positive")
    return active


def scan_properties(obj):
    active_count, zones = 0, set()
    with open_grid(obj) as group:
        for _, data in blocks(group):
            mask = qc_block(data)
            active_count += int(mask.sum())
            zones.update(map(int, np.unique(data["zones"][mask])))
            require(len(zones) <= 10000, "QC_FAILED", "Too many zone IDs")
    require(active_count > 0, "QC_FAILED", "No active cells")
    return dict(active_cells=active_count, zone_ids=sorted(zones), qc_status="PASS")


def _cartesian_volume_block(start, data, order, grid, cases):
    nz, e = grid["shape"][2], grid["extent"]
    spacing = [(e[2 * i + 1] - e[2 * i]) / grid["shape"][i] for i in range(3)]
    cell_volume, dz = math.prod(spacing), spacing[2]
    active = qc_block(data)
    index = np.arange(start, start + len(active), dtype=np.int64)
    top = (
        e[5] - (index // (grid["shape"][0] * grid["shape"][1])) * dz
        if order == "ECLIPSE"
        else e[4] + ((index % nz) + 1) * dz
    )
    parts, counts = [], []
    for case in cases:
        selected = active & np.isin(data["zones"], case["zone_ids"])
        counts.append(int(selected.sum()))
        fraction = np.clip((top[selected] - case["contact_z_m"]) / dz, 0, 1)
        overrides = case.get("overrides", {})
        phi, ntg, sw = [overrides.get(k, data[k][selected]) for k in ("phi", "ntg", "sw")]
        net, pore = fraction * ntg, fraction * ntg * phi
        parts.append(
            (
                np.array(
                    [
                        selected.sum(),
                        fraction.sum(dtype=np.float64),
                        net.sum(dtype=np.float64),
                        pore.sum(dtype=np.float64),
                        (pore * (1 - sw)).sum(dtype=np.float64),
                    ]
                )
                * cell_volume
            ).tolist()
        )
    return parts, counts


def evaluate(obj, cases):
    """One sequential pass for all contacts/realizations; only a bounded block lives in RAM."""
    if obj["summary"].get("storage") == "cornerpoint-zarr-v1":
        from opensubsurface.adapters.cornerpoint import evaluate as evaluate_cornerpoint

        return evaluate_cornerpoint(obj, cases)
    from opensubsurface.execution.blocks import mapped

    totals = [[[] for _ in range(5)] for _ in cases]
    selected_counts = [0] * len(cases)
    for partials, counts in mapped(
        obj, _cartesian_volume_block, obj["summary"]["grid"], cases, include_corners=False
    ):
        for i in range(len(cases)):
            selected_counts[i] += counts[i]
            for target, value in zip(totals[i], partials[i]):
                target.append(value)
    sums = [[math.fsum(part) for part in row] for row in totals]
    results = []
    for case, values, selected in zip(cases, sums, selected_counts):
        require(selected > 0, "QC_FAILED", "Selected zones contain no active cells")
        result = dict(zip(("GRV", "GRV_oil_interval", "NetRockVolume", "PV", "HCPV"), map(float, values)))
        result["STOIIP"] = result["HCPV"] / case["bo"]
        results.append(result)
    return results


def is_large(obj):
    return obj["summary"].get("storage") in (STORAGE, "cornerpoint-zarr-v1")


def input_identity(context):
    return digest({key: context[key] for key in ("manifest_sha256", "headers")})
