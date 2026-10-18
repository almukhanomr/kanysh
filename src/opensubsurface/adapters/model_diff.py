"""Compare immutable revisions by physical IJK and report region bulk/pore-volume impacts."""

import csv
import math

import numpy as np

from opensubsurface.adapters.cornerpoint import cell_volumes
from opensubsurface.adapters.model_arrays import cartesian_corners, ijk, provenance, region
from opensubsurface.calculations.cornerpoint_reference import integral
from opensubsurface.errors import require


def read_other(obj, group, order, shape, start, count, source_order, arrays=None):
    ids = ijk(np.arange(start, start + count), shape, source_order)
    indices = np.ravel_multi_index(ids.T, shape, order="F" if order == "ECLIPSE" else "C")
    if arrays is None:
        names = group.array_keys() if hasattr(group, "array_keys") else group
        arrays = {name: group[name] for name in names}
    data = {}
    for name, array in arrays.items():
        data[name] = np.asarray(array.oindex[indices] if hasattr(array, "oindex") else array[indices])
    if "corners" not in data:
        data["corners"] = cartesian_corners(obj, indices, order)
    return data


def _geometry_block(start, data, order, storage):
    from opensubsurface.adapters.model_qc import jacobians

    c = np.where(np.isfinite(data["corners"]), data["corners"], 0)
    bulk = cell_volumes(c)
    expected = integral(c)
    validation = bool(np.allclose(bulk, expected, rtol=1e-10, atol=1e-8))
    finite_geometry = np.isfinite(data["corners"]).all(axis=(1, 2))
    det = jacobians(c) * (-1 if storage == "cornerpoint-zarr-v1" else 1)
    scale = np.max(np.ptp(c, axis=1), axis=1) ** 3
    valid = finite_geometry & (
        det.min(axis=1) > np.finfo(float).eps * 256 * np.maximum(scale, np.finfo(float).tiny)
    )
    return start, data, order, np.where(valid, bulk, np.nan), validation


def _paired_block(start, data, order, left, right, shape):
    from opensubsurface.execution.blocks import model_layout

    group, other_order, arrays = model_layout(right)
    b = read_other(right, group, other_order, shape, start, len(data["active"]), order, arrays)
    a_result = _geometry_block(start, data, order, left["summary"].get("storage"))
    b_result = _geometry_block(start, b, other_order, right["summary"].get("storage"))
    return start, data, order, b, a_result[3], b_result[3], a_result[4] and b_result[4]


def run(left, right, p, out):
    shape = tuple(left["summary"]["grid"]["shape"])
    require(
        shape == tuple(right["summary"]["grid"]["shape"]),
        "GRID_MAPPING_ERROR",
        "model_diff requires identical IJK topology; no inferred resampling",
    )
    for key in ("crs", "vertical_datum"):
        require(
            left["summary"].get(key) == right["summary"].get(key),
            "INVALID_CRS",
            "Revision coordinate metadata differs; explicit alignment required",
        )
    counts, examples, impact = {}, [], {}
    changed_total = 0
    validation = True
    from opensubsurface.execution.blocks import mapped

    with (out / "changed_cells.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "i",
                "j",
                "k",
                "cell_id",
                "field",
                "before",
                "after",
                "region_before",
                "region_after",
            ],
        )
        writer.writeheader()
        for start, a, order, b, bulk_a, bulk_b, block_ok in mapped(
            left, _paired_block, left, right, shape, execution=p.get("execution")
        ):
            validation &= block_ok
            ia = ijk(np.arange(start, start + len(a["active"])), shape, order)
            regions = [region(a, p["region_field"]), region(b, p["region_field"])]
            changed = np.zeros(len(a["active"]), bool)
            for field in sorted(a.keys() | b.keys()):
                if field not in a or field not in b:
                    mask = np.ones(len(changed), bool)
                else:
                    x, y = a[field], b[field]
                    equal = (
                        (x == y)
                        if field
                        in {"active", "zones", "FIPNUM", "EQLNUM", "SATNUM", "PVTNUM", "fault_blocks"}
                        else np.isclose(x, y, rtol=p["rtol"], atol=p["atol"], equal_nan=True)
                    )
                    mask = ~equal if equal.ndim == 1 else ~equal.all(axis=tuple(range(1, equal.ndim)))
                counts[field] = counts.get(field, 0) + int(mask.sum())
                changed |= mask
                for local in np.flatnonzero(mask):

                    def value(data):
                        if field not in data:
                            return None
                        v = data[field][local]
                        if np.ndim(v):
                            return "geometry changed"
                        return float(v) if np.isfinite(v) else None

                    row = dict(
                        i=int(ia[local, 0]) + 1,
                        j=int(ia[local, 1]) + 1,
                        k=int(ia[local, 2]) + 1,
                        cell_id=int(start + local),
                        field=field,
                        before=value(a),
                        after=value(b),
                        region_before=int(regions[0][local]),
                        region_after=int(regions[1][local]),
                    )
                    writer.writerow(row)
                    if len(examples) < p["max_examples"]:
                        examples.append(row)
            changed_total += int(changed.sum())
            for revision, data, rids in (("before", a, regions[0]), ("after", b, regions[1])):
                active = data["active"].astype(bool)
                bulk = bulk_a if revision == "before" else bulk_b
                phi, ntg, sw = [data.get(k, np.full(len(active), np.nan)) for k in ("phi", "ntg", "sw")]
                phi = np.where((phi >= 0) & (phi <= 1), phi, np.nan)
                ntg = np.where((ntg >= 0) & (ntg <= 1), ntg, np.nan)
                sw = np.where((sw >= 0) & (sw <= 1), sw, np.nan)
                pore = bulk * phi * ntg
                hydrocarbon = pore * (1 - sw)
                for rid in np.unique(rids[active]):
                    selected = active & (rids == rid)
                    row = impact.setdefault(int(rid), {})
                    for name, values in (("GRV", bulk), ("PV", pore), ("HCPV", hydrocarbon)):
                        key = revision + "_" + name
                        total = row.setdefault(key, dict(parts=[], invalid=0))
                        valid = selected & np.isfinite(values)
                        total["parts"].append(float(values[valid].sum()))
                        total["invalid"] += int((selected & ~np.isfinite(values)).sum())
    rows = []
    for rid, record in sorted(impact.items()):
        row = dict(region_id=rid)
        for metric in ("GRV", "PV", "HCPV"):
            for revision in ("before", "after"):
                value = record.get(revision + "_" + metric, dict(parts=[], invalid=0))
                row[revision + "_" + metric] = None if value["invalid"] else math.fsum(value["parts"])
            left_value, right_value = row["before_" + metric], row["after_" + metric]
            row["delta_" + metric] = (
                right_value - left_value if left_value is not None and right_value is not None else None
            )
        rows.append(row)
    return dict(
        operation="model_diff",
        status="CHANGED" if changed_total else "IDENTICAL",
        validation_status="PASS" if validation else "FAIL",
        scope="Same-topology revision comparison by source IJK",
        inputs=[provenance(left), provenance(right)],
        changed_cells=changed_total,
        property_changed_cells=counts,
        examples=examples,
        tables=dict(region_volume_impact=rows),
        assumptions=p["assumptions"],
        tolerances=dict(atol=p["atol"], rtol=p["rtol"]),
        independent_checks=[
            dict(
                name="all_cell_bulk_volumes_vs_independent_determinants",
                status="PASS" if validation else "FAIL",
            )
        ],
        limitations=[
            "Region PV/HCPV here refer to the full active model, without contact clipping or Bo; no STOIIP effect is inferred",
            "Missing/invalid property values produce unavailable volume impacts, never fabricated zeros",
            "Different topology/CRS/datum requires explicit registration and is rejected",
        ],
    )
