"""XTGeo geometry import, explicit property declarations and chunked tetrahedral volumes.

XTGeo import is in-memory and preflight-limited. Subsequent calculations use Zarr blocks.
Cells are defined by six tetrahedra around corner diagonal 0–7, including warped faces.
"""

import hashlib
import math
import os
import re
import shutil
import struct
from contextlib import contextmanager
from pathlib import PurePosixPath

import numpy as np
import zarr
from pydantic import Field, model_validator

from opensubsurface.adapters.grdecl_properties import KEYWORDS, fill
from opensubsurface.adapters.large_grid import FIELDS, UNITS, ArrayFile, qc_block
from opensubsurface.adapters.local_sources import LocalSources, opened_source, parts, revision
from opensubsurface.adapters.source_files import copy_file
from opensubsurface.errors import require
from opensubsurface.schemas import Strict

FORMAT = "opensubsurface.cornerpoint.xtgeo.v1"
STORAGE = "cornerpoint-zarr-v1"
TETS = np.array([[0, 1, 3, 7], [0, 1, 5, 7], [0, 2, 3, 7], [0, 2, 6, 7], [0, 4, 5, 7], [0, 4, 6, 7]])


class GeometryFile(Strict):
    path: str
    file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    format: str


class Manifest(Strict):
    format: str
    shape: tuple[int, int, int]
    geometry: GeometryFile
    crs: str
    vertical_datum: str
    length_unit: str
    z_direction: str
    units: dict[str, str]
    arrays: dict[str, ArrayFile]
    assumptions: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def profile(self):
        if (
            self.format != FORMAT
            or self.geometry.format not in ("grdecl", "egrid", "roff")
            or self.length_unit not in ("m", "ft")
            or self.z_direction not in ("up", "down")
            or self.units != UNITS
            or any(n < 1 for n in self.shape)
            or math.prod(self.shape) > 2_000_000
        ):
            raise ValueError("Corner-point profile: <=2M cells; explicit format/units/Z direction")
        if set(self.arrays) != set(FIELDS) - {"active"}:
            raise ValueError("Six property declarations required; ACTNUM comes from geometry")
        for name, entry in self.arrays.items():
            if entry.constant is None and entry.keyword not in KEYWORDS[name]:
                raise ValueError("One supported GRDECL keyword per property file")
        return self


def prepare(service, p, raw, source):
    import psutil

    manifest = Manifest.model_validate_json(raw).model_dump(mode="json")
    headers = {"geometry": manifest["geometry"]}
    headers.update(manifest["arrays"])
    base, total = PurePosixPath(p["path"]).parent, 0
    headers = {k: dict(v) for k, v in headers.items()}
    for h in headers.values():
        if h.get("constant") is not None:
            continue
        parts(h["path"])
        h["path"] = str(base / h["path"])
        with LocalSources(service.store).opened(p["source_id"], h["path"]) as (fd, _):
            require(revision(os.fstat(fd)) == h["file_revision"], "SOURCE_CHANGED", "Source changed")
            h["size_bytes"] = os.fstat(fd).st_size
            total += h["size_bytes"]
    estimate = math.prod(manifest["shape"]) * 2048 + total * 4 + 256 * 1024**2
    require(
        headers["geometry"]["size_bytes"] <= 512 * 1024**2,
        "UNSUPPORTED_PROFILE",
        "Native geometry file limit 512 MiB",
    )
    require(
        estimate < psutil.virtual_memory().available * 0.6,
        "INSUFFICIENT_MEMORY",
        "XTGeo geometry import requires full RAM; reduce model or add RAM",
    )
    return dict(
        source=source,
        manifest=manifest,
        headers=headers,
        input_bytes=total,
        manifest_path=p["path"],
        manifest_revision=p["file_revision"],
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        import_ram_estimate_bytes=estimate,
    )


def native_shape(path, fmt):
    """Read dimensions before allowing native readers to allocate geometry arrays."""
    if fmt == "grdecl":
        with path.open("rb") as f:
            head = f.read(1024**2).decode("ascii")
        head = re.sub(r"--[^\n]*", "", head)
        match = re.match(r"\s*SPECGRID\s+(\d+)\s+(\d+)\s+(\d+)\s+1\s+[FT]\s*/", head, re.I)
        require(match is not None, "UNSUPPORTED_PROFILE", "GRDECL must start with SPECGRID NX NY NZ 1 F /")
        return tuple(map(int, match.groups()))
    if fmt == "roff":
        import roffio

        with roffio.lazy_read(path) as tags:
            for name, entries in tags:
                require(
                    name in ("filedata", "version", "dimensions"),
                    "UNSUPPORTED_PROFILE",
                    "ROFF dimensions must precede geometry arrays",
                )
                entries = dict(entries)
                if name == "dimensions":
                    return tuple(int(entries[k]) for k in ("nX", "nY", "nZ"))
    else:
        # Unformatted ECLIPSE: keyword records followed by bounded Fortran data records.
        with path.open("rb") as f:
            for _ in range(32):
                header = f.read(24)
                require(
                    len(header) == 24
                    and struct.unpack(">i", header[:4])[0] == 16
                    and struct.unpack(">i", header[-4:])[0] == 16,
                    "INVALID_FORMAT",
                    "Big-endian unformatted EGRID required",
                )
                key, count, kind = header[4:12].strip(), struct.unpack(">i", header[12:16])[0], header[16:20]
                require(
                    0 <= count <= 1024 and kind in (b"INTE", b"CHAR"),
                    "UNSUPPORTED_PROFILE",
                    "EGRID GRIDHEAD must precede large data",
                )
                size = count * (8 if kind == b"CHAR" else 4)
                record = f.read(4)
                require(
                    len(record) == 4 and struct.unpack(">i", record)[0] == size,
                    "INVALID_FORMAT",
                    "Invalid EGRID header record",
                )
                data = f.read(size)
                require(f.read(4) == record, "INVALID_FORMAT", "EGRID record length mismatch")
                if key == b"GRIDHEAD":
                    require(count >= 4 and kind == b"INTE", "INVALID_FORMAT", "Invalid GRIDHEAD")
                    return tuple(map(int, np.frombuffer(data, dtype=">i4")[1:4]))
    require(False, "INVALID_FORMAT", "Grid dimensions not found")


def tetra_volume(t):
    return (
        np.abs(
            np.einsum(
                "...i,...i->...",
                t[..., 1, :] - t[..., 0, :],
                np.cross(t[..., 2, :] - t[..., 0, :], t[..., 3, :] - t[..., 0, :]),
            )
        )
        / 6
    )


def clipped_tetra(t, contact):
    """Exact planar clipping of the declared tetrahedra, including repeated vertex depths."""
    inside = t[..., 2] >= contact
    counts = inside.sum(axis=1)
    result = np.zeros(len(t))
    result[counts == 4] = tetra_volume(t[counts == 4])
    for count in (1, 2, 3):
        mask = counts == count
        a = t[mask]
        if not len(a):
            continue
        order = np.argsort(~inside[mask], axis=1, kind="stable")
        a = np.take_along_axis(a, order[..., None], axis=1)
        if count in (1, 3):
            if count == 3:
                a = a[:, [3, 0, 1, 2]]
            ratio = (contact - a[:, 0, 2, None]) / (a[:, 1:, 2] - a[:, 0, 2, None])
            small = tetra_volume(a) * np.prod(ratio, axis=1)
            result[mask] = small if count == 1 else tetra_volume(a) - small
        else:

            def edge(i, j):
                ratio = (contact - a[:, i, 2]) / (a[:, j, 2] - a[:, i, 2])
                return a[:, i] + ratio[:, None] * (a[:, j] - a[:, i])

            ac, ad, bc, bd = edge(0, 2), edge(0, 3), edge(1, 2), edge(1, 3)
            result[mask] = (
                tetra_volume(np.stack([a[:, 0], a[:, 1], ac, ad], axis=1))
                + tetra_volume(np.stack([a[:, 1], ac, ad, bd], axis=1))
                + tetra_volume(np.stack([a[:, 1], ac, bc, bd], axis=1))
            )
    return result


def cell_volumes(corners, contact=None):
    result = np.zeros(len(corners))
    for tet in TETS:
        t = corners[:, tet]
        result += tetra_volume(t) if contact is None else clipped_tetra(t, contact)
    return result


def import_grid(context, block_cells, out):
    import xtgeo

    from opensubsurface.adapters.large_grid import check_source

    m, headers = context["manifest"], context["headers"]
    cells = math.prod(m["shape"])
    step = min(block_cells, 16384)
    require(
        shutil.disk_usage(out).free > cells * 600 + context["input_bytes"] * 2,
        "INSUFFICIENT_DISK",
        "Need native snapshot, Zarr and publication space",
    )
    path = out / ("geometry." + m["geometry"]["format"])
    geometry_hash = copy_file(context, headers["geometry"], path)
    require(
        native_shape(path, m["geometry"]["format"]) == tuple(m["shape"]),
        "GRID_MAPPING_ERROR",
        "Native dimensions disagree with manifest",
    )
    if m["geometry"]["format"] in ("grdecl", "egrid"):
        with path.open("rb") as f:
            overlap = b""
            while raw := f.read(1024**2):
                forbidden = (
                    re.search(
                        rb"\b(INCLUDE|BOX|ENDBOX|EDIT|MULTIPLY|ADD|COPY|LGR|CARFIN|ENDFIN)\b",
                        overlap + raw,
                        re.I,
                    )
                    if m["geometry"]["format"] == "grdecl"
                    else b"\x00\x00\x00\x10LGR     " in overlap + raw
                )
                require(
                    not forbidden,
                    "UNSUPPORTED_PROFILE",
                    "Self-contained global grid only; no INCLUDE/edits/LGR",
                )
                overlap = raw[-32:]
    grid = xtgeo.grid_from_file(path, fformat=m["geometry"]["format"])
    require(
        grid.units is None or grid.units.name == ("METRES" if m["length_unit"] == "m" else "FEET"),
        "INVALID_UNITS",
        "Native grid units conflict with explicit declaration",
    )
    require(
        tuple(grid.dimensions) == tuple(m["shape"]) and not grid.dualporo and not grid.dualperm,
        "UNSUPPORTED_PROFILE",
        "Single-porosity corner-point grid required",
    )
    # Native IJK corner properties allow explicit, tested C-order mapping without guessed VTK ordering.
    native = grid.get_xyz_corners()
    active = grid.get_actnum(asmasked=False).values.ravel(order="C")
    require(np.isin(active, [0, 1]).all(), "QC_FAILED", "Only ACTNUM 0/1 supported")
    scale = 0.3048 if m["length_unit"] == "ft" else 1.0
    low, high = np.full(3, np.inf), np.full(3, -np.inf)
    hashes = {"geometry": geometry_hash}
    with zarr.ZipStore(str(out / "grid.zip"), mode="w") as store:
        group = zarr.group(store=store)
        group.attrs.update(storage=STORAGE, shape=m["shape"], order="C", z_direction="up")
        corners = group.create_dataset(
            "corners", shape=(cells, 8, 3), chunks=(min(step, cells), 8, 3), dtype="f8"
        )
        for start in range(0, cells, step):
            end = min(start + step, cells)
            data = np.stack([v.values.ravel(order="C")[start:end] for v in native], axis=1).reshape(-1, 8, 3)
            data *= scale
            if m["z_direction"] == "down":
                data[:, :, 2] *= -1
            mask = active[start:end] == 1
            require(np.isfinite(data[mask]).all(), "QC_FAILED", "Nonfinite active cell corners")
            if mask.any():
                low = np.minimum(low, data[mask].min(axis=(0, 1)))
                high = np.maximum(high, data[mask].max(axis=(0, 1)))
            corners[start:end] = data
        group.create_dataset("active", data=active.astype(bool), chunks=(min(step, cells),))
        for name in FIELDS[1:]:
            h = headers[name]
            target = group.create_dataset(
                name, shape=(cells,), chunks=(min(step, cells),), dtype="i4" if name == "zones" else "f8"
            )
            if h.get("constant") is not None:
                value = h["constant"]
                require(
                    name != "zones" or (value == int(value) and 1 <= value <= 2**31 - 1),
                    "QC_FAILED",
                    "Positive integer zone required",
                )
                for start in range(0, cells, step):
                    target[start : min(start + step, cells)] = value
                hashes[name] = hashlib.sha256((name + ":" + repr(value)).encode()).hexdigest()
            else:
                # Exported property files are I-fast/K-down; preserve that physical IJK mapping.
                temporary = np.empty(cells, dtype=target.dtype)
                with opened_source(context["source"], h["path"]) as (fd, _):
                    sha = hashlib.sha256()
                    fill(fd, temporary, h["keyword"], cells, step, sha)
                    require(
                        revision(os.fstat(fd)) == h["file_revision"], "SOURCE_CHANGED", "Property changed"
                    )
                data = temporary.reshape(tuple(m["shape"]), order="F").ravel(order="C")
                if name == "kz_ratio":
                    for start in range(0, cells, step):
                        kx = group["permeability_md"][start : start + step]
                        data[start : start + step] = np.divide(
                            data[start : start + step], kx, out=np.full_like(kx, np.nan), where=kx > 0
                        )
                target[:] = data
                hashes[name] = sha.hexdigest()
    require(np.isfinite(low).all() and np.all(high > low), "QC_FAILED", "No active 3D cells")
    check_source(context)
    extent = [float(v) for pair in zip(low, high) for v in pair]
    summary = dict(
        storage=STORAGE,
        source_format=m["format"],
        grid=dict(shape=m["shape"], extent=extent),
        block_cells=step,
        cells=cells,
        crs=m["crs"],
        vertical_datum=m["vertical_datum"],
        z_direction="up",
        order="C",
        units=UNITS,
        source_sha256=hashes,
        source_input_bytes=context["input_bytes"],
        manifest_sha256=context["manifest_sha256"],
        input_declarations=m,
        backend="cornerpoint-tetra6-cpu",
        geometry_profile="diagonal-0-7-tetra6",
        import_ram_estimate_bytes=context["import_ram_estimate_bytes"],
        working_memory_bound_bytes=step * 2048,
        assumptions=m["assumptions"],
        xtgeo_version=xtgeo.__version__,
    )
    obj = dict(summary=summary, paths={"grid.zip": str(out / "grid.zip")})
    summary.update(scan_properties(obj))
    return "properties", summary, {"grid.zip": out / "grid.zip", path.name: path}


@contextmanager
def open_grid(obj):
    with zarr.ZipStore(obj["paths"]["grid.zip"], mode="r") as store:
        group = zarr.open_group(store=store, mode="r")
        cells = math.prod(obj["summary"]["grid"]["shape"])
        require(
            group.attrs["storage"] == STORAGE
            and group.attrs["order"] in ("C", "ECLIPSE")
            and group.attrs["shape"] == obj["summary"]["grid"]["shape"]
            and set(FIELDS) | {"corners"} <= set(group.array_keys())
            and set(group.array_keys())
            <= set(FIELDS) | {"corners", "FIPNUM", "SATNUM", "EQLNUM", "PVTNUM", "PERMY", "PERMZ"},
            "INTEGRITY_ERROR",
            "Grid metadata",
        )
        for name, a in group.arrays():
            geometry = name == "corners"
            require(
                a.shape == ((cells, 8, 3) if geometry else (cells,))
                and a.chunks[0] <= 16384
                and a.chunks[0] >= 1
                and a.dtype.kind
                in (
                    "f"
                    if geometry
                    else "bui"
                    if name in ("active", "zones", "FIPNUM", "SATNUM", "EQLNUM", "PVTNUM")
                    else "f"
                ),
                "INTEGRITY_ERROR",
                "Grid array layout",
            )
            count = math.ceil(cells / a.chunks[0])
            suffix = ".0.0" if geometry else ""
            require(
                all(f"{name}/{i}{suffix}" in store for i in range(count)),
                "INTEGRITY_ERROR",
                "Missing geometry/property chunk",
            )
        yield group


def blocks(group):
    cells, step = group["active"].shape[0], group["active"].chunks[0]
    arrays = {name: group[name] for name in group.array_keys()}
    for start in range(0, cells, step):
        yield start, {name: np.asarray(array[start : start + step]) for name, array in arrays.items()}


def scan_properties(obj):
    count, zones = 0, set()
    with open_grid(obj) as group:
        for _, data in blocks(group):
            mask = qc_block(data)
            v = cell_volumes(data["corners"][mask])
            require(np.isfinite(v).all() and (v > 0).all(), "QC_FAILED", "Nonpositive active cell volume")
            count += int(mask.sum())
            zones.update(map(int, np.unique(data["zones"][mask])))
    require(count > 0 and len(zones) <= 10000, "QC_FAILED", "Invalid active cells/zones")
    return dict(active_cells=count, zone_ids=sorted(zones), qc_status="PASS")


def _volumes_block(start, data, order, cases, device):
    volumes = cell_volumes
    if device == "cuda":
        from opensubsurface.execution.cornerpoint_gpu import cell_volumes as volumes
    active = qc_block(data)
    from opensubsurface.adapters.model_qc import geometry_flags

    valid = geometry_flags(data["corners"], STORAGE)["valid"]
    parts, counts = [], []
    for case in cases:
        mask = active & np.isin(data["zones"], case["zone_ids"])
        require(
            not (mask & ~valid).any(),
            "INVALID_GEOMETRY",
            "Selected imported cells fail strict geometry checks",
            "zone_ids",
            "Run model_qc; select valid zones or use regional_volumes with explicit confirmed exclusions",
        )
        counts.append(int(mask.sum()))
        corners = data["corners"][mask]
        bulk, oil = volumes(corners), volumes(corners, case["contact_z_m"])
        override = case.get("overrides", {})
        phi, ntg, sw = [override.get(k, data[k][mask]) for k in ("phi", "ntg", "sw")]
        net, pore = oil * ntg, oil * ntg * phi
        parts.append([float(np.sum(v, dtype=np.float64)) for v in (bulk, oil, net, pore, pore * (1 - sw))])
    return parts, counts


def evaluate(obj, cases):
    from opensubsurface.execution.blocks import mapped, settings

    sums = [[[] for _ in range(5)] for _ in cases]
    counts = [0] * len(cases)
    device = settings.get().get("resolved_device", "cpu")
    for partials, nums in mapped(obj, _volumes_block, cases, device):
        for i in range(len(cases)):
            counts[i] += nums[i]
            for target, value in zip(sums[i], partials[i]):
                target.append(value)
    result = []
    for i, case in enumerate(cases):
        require(counts[i] > 0, "QC_FAILED", "No active selected cells")
        values = dict(
            zip(
                ("GRV", "GRV_oil_interval", "NetRockVolume", "PV", "HCPV"),
                [math.fsum(values) for values in sums[i]],
            )
        )
        values["STOIIP"] = values["HCPV"] / case["bo"]
        result.append(values)
    return result
