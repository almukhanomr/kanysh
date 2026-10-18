"""Out-of-core COORD/ZCORN reconstruction and static DATA import."""

import json
import math
import shutil

import numpy as np
import zarr

from opensubsurface.adapters.cornerpoint import STORAGE
from opensubsurface.adapters.eclipse_deck import Interpreter, discard_pages
from opensubsurface.adapters.large_grid import FIELDS, UNITS
from opensubsurface.adapters.local_sources import opened_source, revision
from opensubsurface.errors import require
from opensubsurface.execution import progress

PROPERTIES = dict(active="ACTNUM", zones="FIPNUM", phi="PORO", ntg="NTG", sw="SWAT", permeability_md="PERMX")


def reconstruct(coord, zcorn, shape, start, end, scale, z_direction, mapaxes=None):
    """Gather only one cell block from ECLIPSE pillar/ZCORN order, without full transpose."""
    nx, ny, _ = shape
    ids = np.arange(start, end, dtype=np.int64)
    i, j, k = ids % nx, (ids // nx) % ny, ids // (nx * ny)
    result = np.empty((end - start, 8, 3))
    for corner in range(8):
        di, dj, dk = corner % 2, (corner // 2) % 2, corner // 4
        indices = ((2 * k + dk) * 2 * ny + (2 * j + dj)) * 2 * nx + 2 * i + di
        z = np.asarray(zcorn[indices])
        pillars = np.asarray(coord.reshape(-1, 6)[(j + dj) * (nx + 1) + i + di])
        dz = pillars[:, 5] - pillars[:, 2]
        ratio = np.divide(z - pillars[:, 2], dz, out=np.zeros(len(z)), where=dz != 0)
        require(
            np.all((dz != 0) | (np.abs(z - pillars[:, 2]) < 1e-9)),
            "INVALID_GEOMETRY",
            "Zero-height pillar has off-pillar ZCORN",
        )
        result[:, corner, :2] = pillars[:, :2] + ratio[:, None] * (pillars[:, 3:5] - pillars[:, :2])
        result[:, corner, 2] = z
    return to_world(result, scale, z_direction, mapaxes)


def to_world(result, scale, z_direction, mapaxes=None):
    """Grid-local corners -> map coordinates (MAPAXES), metres, Z positive upward."""
    if mapaxes is not None:
        axes = np.asarray(mapaxes).reshape(3, 2)
        origin = axes[1]
        x_axis, y_axis = axes[2] - origin, axes[0] - origin
        require(
            np.linalg.norm(x_axis) > 0 and np.linalg.norm(y_axis) > 0,
            "INVALID_GEOMETRY",
            "Degenerate MAPAXES",
        )
        x_axis, y_axis = x_axis / np.linalg.norm(x_axis), y_axis / np.linalg.norm(y_axis)
        require(abs(np.dot(x_axis, y_axis)) < 1e-6, "UNSUPPORTED_PROFILE", "Non-orthogonal MAPAXES")
        result[:, :, :2] = origin + result[:, :, 0, None] * x_axis + result[:, :, 1, None] * y_axis
    result *= scale
    if z_direction == "down":
        result[:, :, 2] *= -1
    return result


def import_deck(context, p, out):
    work = out / "deck-work"
    work.mkdir()
    binary = p.get("format") == "egrid" or (
        p.get("format", "auto") == "auto" and p["path"].lower().endswith((".egrid", ".grid"))
    )
    if binary:
        from opensubsurface.adapters.eclipse_binary import parse

        deck = parse(context["source"], p, work)
    else:
        require(
            not p.get("property_files"),
            "UNSUPPORTED_PROFILE",
            "property_files is supported for EGRID imports",
        )
        deck = Interpreter(context["source"], p["path"], work, p["file_revision"]).parse()
    cells, step = math.prod(deck.shape), min(p["block_cells"], 16384)
    from opensubsurface.execution.resources import disk_check

    disk_check(out, cells * 500)
    require(
        {"COORD", "ZCORN"} <= deck.arrays.keys(),
        "MISSING_GEOMETRY",
        "COORD and ZCORN required; Cartesian DATA geometry not supported here",
    )
    declared = {"METRIC": "m", "FIELD": "ft"}.get(deck.unit)
    require(deck.unit != "LAB", "UNSUPPORTED_PROFILE", "LAB units not supported")
    require(
        declared in (None, p["length_unit"]),
        "INVALID_UNITS",
        "User-confirmed length unit conflicts with deck",
    )
    for proposal in deck.suggestions:
        if proposal["parameter"] in ("GRIDUNIT", "MAPUNITS"):
            values = [value.strip("' ").upper() for value in proposal["tokens"]]
            units = {"METRES": "m", "METERS": "m", "M": "m", "FEET": "ft", "FT": "ft"}
            require(
                values and units.get(values[0]) == p["length_unit"] and not any(values[1:]),
                "UNSUPPORTED_PROFILE",
                "Mixed GRIDUNIT/MAPUNITS or non-default map-unit mode requires explicit conversion before import",
            )
    for name, value in p["defaults"].items():
        require(
            name not in deck.arrays,
            "INVALID_ARGUMENTS",
            "Default cannot replace an existing property: " + name,
        )
        a = deck.array(name)
        for start in range(0, len(a), 65536):
            a[start : start + 65536] = value
            a = deck.arrays[name] = discard_pages(a, dirty=(start, min(start + 65536, len(a))))
    # Parsed scratch arrays are immutable from this point. Read-only remaps release
    # resident pages without repeatedly flushing multi-GB mappings on Windows.
    for name, array in list(deck.arrays.items()):
        deck.arrays[name] = discard_pages(array, readonly=True, dirty=(0, 0))
    require(
        "ACTNUM" in deck.arrays, "MISSING_PROPERTY", "ACTNUM missing; provide explicit user-confirmed default"
    )
    mapping = dict(PROPERTIES, zones=p["region_field"])
    missing = [name for name in mapping.values() if name not in deck.arrays]
    hashes = {item["path"]: item["sha256"] for item in deck.files}
    low, high = np.full(3, np.inf), np.full(3, -np.inf)
    active_count, regions = 0, set()
    region_values = {}
    extra = [key for key in ("FIPNUM", "SATNUM", "EQLNUM", "PVTNUM", "PERMY", "PERMZ") if key in deck.arrays]
    with zarr.ZipStore(str(out / "grid.zip"), mode="w") as store:
        group = zarr.group(store=store)
        group.attrs.update(storage=STORAGE, shape=list(deck.shape), order="ECLIPSE", z_direction="up")
        group.create_dataset("corners", shape=(cells, 8, 3), chunks=(step, 8, 3), dtype="f8")
        for name in (*FIELDS, *extra):
            group.create_dataset(
                name,
                shape=(cells,),
                chunks=(step,),
                dtype="bool"
                if name == "active"
                else "i4"
                if name in ("zones", "FIPNUM", "SATNUM", "EQLNUM", "PVTNUM")
                else "f8",
            )
        targets = {name: group[name] for name in group.array_keys()}
        for start in range(0, cells, step):
            progress.report(0.5 * start / cells, "eclipse_import: geometry/property blocks")
            end = min(cells, start + step)
            corners = (
                # Legacy .GRID: the simulator's own corners, not a pillar reconstruction.
                to_world(
                    np.asarray(deck.grid_corners[start:end], dtype=np.float64),
                    0.3048 if p["length_unit"] == "ft" else 1.0,
                    p["z_direction"],
                    deck.mapaxes,
                )
                if getattr(deck, "grid_corners", None) is not None
                else None
            )
            corners = (
                corners
                if corners is not None
                else reconstruct(
                    deck.arrays["COORD"],
                    deck.arrays["ZCORN"],
                    deck.shape,
                    start,
                    end,
                    0.3048 if p["length_unit"] == "ft" else 1.0,
                    p["z_direction"],
                    deck.mapaxes,
                )
            )
            active = np.asarray(deck.arrays["ACTNUM"][start:end])
            require(np.isin(active, [0, 1]).all(), "INVALID_PROPERTY", "ACTNUM requires 0/1")
            mask = active == 1
            if mask.any():
                require(np.isfinite(corners[mask]).all(), "INVALID_GEOMETRY", "Nonfinite active coordinates")
                low = np.minimum(low, corners[mask].min(axis=(0, 1)))
                high = np.maximum(high, corners[mask].max(axis=(0, 1)))
            active_count += int(mask.sum())
            targets["corners"][start:end] = corners
            for name, source in mapping.items():
                values = (
                    np.asarray(deck.arrays[source][start:end])
                    if source in deck.arrays
                    else np.full(end - start, 0 if name == "zones" else np.nan)
                )
                if name == "zones":
                    require(
                        np.isfinite(values).all()
                        and (values == np.floor(values)).all()
                        and (values >= 0).all()
                        and (values <= 2**31 - 1).all(),
                        "INVALID_PROPERTY",
                        "Integer region values required",
                    )
                    regions.update(map(int, np.unique(values[mask])))
                targets[name][start:end] = values
            for name in extra:
                values = np.asarray(deck.arrays[name][start:end])
                if name.endswith("NUM"):
                    require(
                        np.isfinite(values).all()
                        and (values == np.floor(values)).all()
                        and (values >= 0).all()
                        and (values <= 2**31 - 1).all(),
                        "INVALID_PROPERTY",
                        "Invalid region ID",
                    )
                targets[name][start:end] = values
                if name.endswith("NUM"):
                    region_values.setdefault(name, set()).update(map(int, np.unique(values[mask])))
            kx = np.asarray(targets["permeability_md"][start:end])
            kz = (
                np.asarray(deck.arrays["PERMZ"][start:end])
                if "PERMZ" in deck.arrays
                else np.full(end - start, np.nan)
            )
            targets["kz_ratio"][start:end] = np.divide(kz, kx, out=np.full_like(kz, np.nan), where=kx > 0)
            for name, a in list(deck.arrays.items()):
                deck.arrays[name] = discard_pages(a)
    require(active_count > 0 and np.isfinite(low).all(), "INVALID_GEOMETRY", "No active finite cells")
    # Independently check every stored property's preservation using sequential source slices.
    preserved = True
    with zarr.ZipStore(str(out / "grid.zip"), mode="r") as store:
        group = zarr.open_group(store=store)
        targets = {name: group[name] for name in group.array_keys()}
        for name, source in {**mapping, **{name: name for name in extra}}.items():
            if source not in deck.arrays:
                continue
            for start in range(0, cells, step):
                actual = np.asarray(targets[name][start : start + step])
                expected = np.array(deck.arrays[source][start : start + step])
                preserved &= bool(np.array_equal(actual, expected, equal_nan=True))
                deck.arrays[source] = discard_pages(deck.arrays[source])
        for start in range(0, cells, step):
            kx = (
                np.array(deck.arrays["PERMX"][start : start + step])
                if "PERMX" in deck.arrays
                else np.full(min(step, cells - start), np.nan)
            )
            kz = (
                np.array(deck.arrays["PERMZ"][start : start + step])
                if "PERMZ" in deck.arrays
                else np.full(len(kx), np.nan)
            )
            expected = np.divide(kz, kx, out=np.full_like(kx, np.nan), where=kx > 0)
            preserved &= bool(
                np.array_equal(
                    np.asarray(targets["kz_ratio"][start : start + step]), expected, equal_nan=True
                )
            )
            for key in ("PERMX", "PERMZ"):
                if key in deck.arrays:
                    deck.arrays[key] = discard_pages(deck.arrays[key])
    require(preserved, "VALIDATION_FAILED", "Imported property differs from parsed source")
    region_values["zones"] = regions
    region_ids = {name: sorted(values) for name, values in region_values.items()}
    z_convention = dict(
        input_z_direction=p["z_direction"],
        stored_z_direction="up",
        conversion="z_stored = -depth" if p["z_direction"] == "down" else "z_stored = z",
        input_length_unit=p["length_unit"],
        stored_length_unit="m",
        length_scale=0.3048 if p["length_unit"] == "ft" else 1.0,
        example=(
            "ZCORN depth 2692 m is stored as Z=-2692; give contacts as owc_z_m=-2692"
            if p["z_direction"] == "down"
            else "Z values are stored unchanged (positive upward)"
        ),
    )
    report = dict(
        operation="eclipse_import",
        status="PASS",
        z_convention=z_convention,
        region_ids=region_ids,
        scope="Static model import, not simulator initialization or geological validation",
        dimensions=list(deck.shape),
        cells=cells,
        active_cells=active_count,
        source_files=deck.files,
        unsupported_keywords=deck.unsupported,
        applied_edits=deck.applied,
        missing_properties=missing,
        suggestions=deck.suggestions,
        grid_reconstruction=getattr(deck, "grid_reconstruction", None),
        assumptions=p["assumptions"],
        explicit_defaults=p["defaults"],
        checks=[
            dict(name="all_stored_properties_preserved", status="PASS"),
            dict(name="numerical_volumes", status="NOT RUN"),
            dict(name="geological_fitness", status="NOT RUN"),
        ],
        limitations=[
            "MINPV/PINCH, simulator transmissibilities and equilibrium are not applied",
            "Missing properties remain unavailable, never inferred",
            "Only the explicitly declared static arrays/edits are applied",
        ],
    )
    (out / "import_report.json").write_text(
        json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8"
    )
    from opensubsurface.adapters.copilot_report import write_report

    report_files = write_report(out, "ECLIPSE static import", report)
    summary = dict(
        storage=STORAGE,
        source_format="opensubsurface.eclipse.binary.v1" if binary else "opensubsurface.eclipse.static.v1",
        grid=dict(shape=list(deck.shape), extent=[float(v) for pair in zip(low, high) for v in pair]),
        cells=cells,
        active_cells=active_count,
        zone_ids=sorted(regions),
        region_field=p["region_field"],
        available_regions=[n for n in extra if n.endswith("NUM")],
        crs=p["crs"],
        vertical_datum=p["vertical_datum"],
        units=UNITS,
        z_direction="up",
        input_z_direction=p["z_direction"],
        stored_z_direction="up",
        z_conversion=z_convention["conversion"],
        z_convention=z_convention,
        region_ids=region_ids,
        order="ECLIPSE",
        block_cells=step,
        working_memory_bound_bytes=step * 2048,
        source_sha256=hashes,
        assumptions=p["assumptions"],
        source_input_bytes=sum(v["size_bytes"] for v in deck.files),
        geometry_profile="diagonal-0-7-tetra6",
        backend="cornerpoint-blocks-cpu",
        missing_properties=missing,
        qc_status="NOT RUN",
        import_validation="PASS",
        unsupported_keywords=sorted({v["keyword"] for v in deck.unsupported}),
    )
    # Verify registered paths still name the revision actually read, including nested INCLUDE.
    import os

    for item in deck.files:
        with opened_source(context["source"], item["path"]) as (fd, _):
            require(
                revision(os.fstat(fd)) == item["file_revision"],
                "SOURCE_CHANGED",
                "INCLUDE changed before publication",
            )
    for a in deck.arrays.values():
        a._mmap.close()
    if getattr(deck, "grid_corners", None) is not None:
        deck.grid_corners._mmap.close()
    shutil.rmtree(work)
    return (
        "properties",
        summary,
        {**report_files, "grid.zip": out / "grid.zip", "import_report.json": out / "import_report.json"},
    )
