"""Numerical geometry/property QC, with IJK witnesses and topological cluster accounting."""

import csv
import math

import numpy as np
from scipy import ndimage

from opensubsurface.adapters.cornerpoint import cell_volumes
from opensubsurface.adapters.model_arrays import ijk, iterate, provenance, region
from opensubsurface.calculations.cornerpoint_reference import integral


def jacobians(corners):
    offsets = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]]
    )
    # 2x2x2 Gauss rule integrates the trilinear Jacobian determinant; vertex
    # determinants additionally detect local collapse/twist near cell corners.
    lo, hi = (1 - 1 / math.sqrt(3)) / 2, (1 + 1 / math.sqrt(3)) / 2
    gauss = np.where(offsets, hi, lo)
    values = []
    translated = corners - corners[:, :1]
    for point in np.vstack((gauss, offsets)):
        derivative = np.empty((8, 3))
        for dimension in range(3):
            other = [d for d in range(3) if d != dimension]
            weight = np.prod(np.where(offsets[:, other], point[other], 1 - point[other]), axis=1)
            derivative[:, dimension] = np.where(offsets[:, dimension], 1, -1) * weight
        matrix = np.einsum("nci,cj->nij", translated, derivative)
        values.append(np.linalg.det(matrix))
    return np.stack(values, axis=1)


def run(obj, p, out):
    shape = obj["summary"]["grid"]["shape"]
    cells = math.prod(shape)
    active_all = np.empty(cells, bool)
    counts, examples, summaries = {}, [], {}
    independent_ok, checked = True, 0
    with (out / "issues.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["severity", "code", "i", "j", "k", "cell_id", "region"])
        writer.writeheader()

        def issue(mask, severity, code, start, indices, regions):
            ids = np.flatnonzero(mask)
            counts[code] = counts.get(code, 0) + len(ids)
            for local in ids:
                row = dict(
                    severity=severity,
                    code=code,
                    i=int(indices[local, 0]) + 1,
                    j=int(indices[local, 1]) + 1,
                    k=int(indices[local, 2]) + 1,
                    cell_id=int(start + local),
                    region=int(regions[local]),
                )
                writer.writerow(row)
                if len(examples) < p["max_examples"]:
                    examples.append(row)

        for start, data, order in iterate(obj):
            active = data["active"].astype(bool)
            active_all[start : start + len(active)] = active
            ids = ijk(np.arange(start, start + len(active)), shape, order)
            regions = region(data, p["region_field"])
            c = data["corners"]
            finite = np.isfinite(c).all(axis=(1, 2))
            issue(active & ~finite, "ERROR", "nonfinite_geometry", start, ids, regions)
            safe = np.where(np.isfinite(c), c, 0)
            determinants = jacobians(safe)
            orientation = -1 if obj["summary"].get("storage") == "cornerpoint-zarr-v1" else 1
            determinants *= orientation
            scale = np.max(np.ptp(safe, axis=1), axis=1) ** 3
            tolerance = np.finfo(float).eps * 256 * np.maximum(scale, np.finfo(float).tiny)
            signed = determinants[:, :8].mean(axis=1)
            volume = cell_volumes(safe)
            reference = integral(safe)
            independent_ok &= bool(np.allclose(volume, reference, rtol=1e-10, atol=1e-8))
            checked += len(active)
            issue(
                active & finite & (signed < -tolerance),
                "ERROR",
                "negative_signed_volume",
                start,
                ids,
                regions,
            )
            issue(
                active
                & finite
                & (np.min(determinants, axis=1) < -tolerance)
                & (np.max(determinants, axis=1) > tolerance),
                "ERROR",
                "twisted_cell",
                start,
                ids,
                regions,
            )
            issue(
                active
                & finite
                & ((volume <= tolerance) | (np.min(np.abs(determinants), axis=1) <= tolerance)),
                "ERROR",
                "degenerate_cell",
                start,
                ids,
                regions,
            )
            for name in ("phi", "ntg", "sw", "permeability_md", "kz_ratio"):
                values = np.asarray(data.get(name, np.full(len(active), np.nan)))
                bad = ~np.isfinite(values) | (values < 0)
                if name in ("phi", "ntg", "sw"):
                    bad |= values > 1
                issue(active & bad, "ERROR", "property_range:" + name, start, ids, regions)
            phi, ntg = data["phi"], data["ntg"]
            issue(active & (ntg == 0) & (phi > 0), "WARNING", "ntg_zero_with_porosity", start, ids, regions)
            pore = volume * phi * ntg
            issue(active & np.isfinite(pore) & (pore <= 0), "ERROR", "zero_pore_volume", start, ids, regions)
            for rid in np.unique(regions[active]):
                selected = active & (regions == rid)
                row = summaries.setdefault(
                    int(rid),
                    dict(region_id=int(rid), active_cells=0, GRV_m3=0.0, PV_m3=0.0, invalid_pore_cells=0),
                )
                row["active_cells"] += int(selected.sum())
                row["GRV_m3"] += float(volume[selected].sum())
                good = selected & np.isfinite(pore)
                row["PV_m3"] += float(pore[good].sum())
                row["invalid_pore_cells"] += int((selected & ~np.isfinite(pore)).sum())
        labels, number = ndimage.label(
            active_all.reshape(shape, order="F" if order == "ECLIPSE" else "C"),
            structure=ndimage.generate_binary_structure(3, 1),
        )
        sizes = np.bincount(labels.ravel())[1:]
        small = np.flatnonzero(sizes <= p["small_cluster_cells"]) + 1
        cluster_rows = []
        first = np.full(number + 1, cells, np.int64)
        flat = labels.ravel()
        for start in range(0, cells, 16384):
            np.minimum.at(first, flat[start : start + 16384], np.arange(start, min(cells, start + 16384)))
        for cluster in small:
            index = np.array(np.unravel_index(first[cluster], shape))
            row = dict(
                cluster_id=int(cluster),
                cells=int(sizes[cluster - 1]),
                first_ijk=(index + 1).tolist(),
                severity="WARNING",
            )
            writer.writerow(
                dict(
                    severity="WARNING",
                    code="small_isolated_cluster",
                    i=int(index[0] + 1),
                    j=int(index[1] + 1),
                    k=int(index[2] + 1),
                    cell_id=int(
                        np.ravel_multi_index(tuple(index), shape, order="F" if order == "ECLIPSE" else "C")
                    ),
                    region="",
                )
            )
            if len(cluster_rows) < p["max_examples"]:
                cluster_rows.append(row)
        counts["small_isolated_clusters"] = len(small)
    return dict(
        operation="model_qc",
        status="ISSUES"
        if any(v for k, v in counts.items() if k not in {"ntg_zero_with_porosity", "small_isolated_clusters"})
        else "PASS",
        validation_status="PASS" if independent_ok and int(sizes.sum()) == int(active_all.sum()) else "FAIL",
        scope="Numerical model QC; geological fitness requires review",
        input=provenance(obj),
        region_field=p["region_field"],
        assumptions=p["assumptions"],
        counts=counts,
        examples=examples,
        tables=dict(regions=list(summaries.values()), small_clusters=cluster_rows[: p["max_examples"]]),
        clusters=dict(
            total=int(number),
            largest_cells=int(sizes.max()) if len(sizes) else 0,
            threshold_cells=p["small_cluster_cells"],
        ),
        independent_checks=[
            dict(
                name="tetra_einsum_vs_independent_determinants",
                status="PASS" if independent_ok else "FAIL",
                cells=checked,
            ),
            dict(
                name="active_cluster_accounting",
                status="PASS" if int(sizes.sum()) == int(active_all.sum()) else "FAIL",
            ),
        ],
        limitations=[
            "Clusters use IJK six-neighbour ACTNUM connectivity, not fault transmissibility or flow connectivity",
            "NTG=0 with positive PORO is a review warning, not inherently invalid geology",
            "Signed trilinear Jacobians diagnose geometry; volume reporting retains declared six-tetrahedron convention",
        ],
    )
