"""Numerical geometry/property QC, with IJK witnesses and topological cluster accounting."""

import csv
import math

import numpy as np
from scipy import ndimage

from opensubsurface.adapters.cornerpoint import cell_volumes
from opensubsurface.adapters.model_arrays import ijk, iterate, provenance, region
from opensubsurface.calculations.cornerpoint_reference import integral
from opensubsurface.execution import progress

SOURCE_KEYWORDS = dict(phi="PORO", ntg="NTG", sw="SWAT", permeability_md="PERMX")


def missing_properties(obj):
    """Model properties declared absent at import (ECLIPSE keyword names in the summary)."""
    absent = set(obj["summary"].get("missing_properties") or [])
    return [name for name, keyword in SOURCE_KEYWORDS.items() if keyword in absent or name in absent]


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


def geometry_flags(corners, storage=None):
    """Classify cells by trilinear Jacobians; columns 0..7 are Gauss points, 8..15 the vertices.

    Corner k and k+4 lie on the same pillar (offsets differ only in the local z bit). A pillar
    collapsed to zero length (corner-point pinch-out) makes both vertex Jacobians on it exactly
    zero, although the cell is a valid wedge with positive six-tetrahedron volume. Such zeros
    are explained, not degenerate. Any negative Jacobian, a zero at a Gauss point or an
    unexplained vertex zero remains invalid. Tolerances are unchanged: 256 eps L^3 (L = largest
    corner extent) for determinants and 256 eps L for pillar lengths.
    """
    finite = np.isfinite(corners).all(axis=(1, 2))
    safe = np.where(np.isfinite(corners), corners, 0)
    determinants = jacobians(safe) * (-1 if storage == "cornerpoint-zarr-v1" else 1)
    extent = np.maximum(np.max(np.ptp(safe, axis=1), axis=1), np.finfo(float).tiny)
    tolerance = np.finfo(float).eps * 256 * np.maximum(extent**3, np.finfo(float).tiny)
    pillar_tolerance = np.finfo(float).eps * 256 * extent
    collapsed = np.linalg.norm(safe[:, 4:] - safe[:, :4], axis=2) <= pillar_tolerance[:, None]
    vertex = determinants[:, 8:]
    zero = np.abs(determinants) <= tolerance[:, None]
    explained = np.concatenate(
        (np.zeros_like(collapsed, shape=(len(safe), 8)), np.tile(collapsed, 2) & zero[:, 8:]), axis=1
    )
    volume = cell_volumes(safe)
    negative = determinants[:, :8].mean(axis=1) < -tolerance
    twisted = (determinants.min(axis=1) < -tolerance) & (determinants.max(axis=1) > tolerance)
    degenerate = (volume <= tolerance) | (zero & ~explained).any(axis=1)
    valid = finite & ((determinants > tolerance[:, None]) | explained).all(axis=1) & (volume > tolerance)
    return dict(
        finite=finite,
        safe=safe,
        determinants=determinants,
        tolerance=tolerance,
        volume=volume,
        negative=finite & negative,
        twisted=finite & twisted,
        degenerate=finite & degenerate,
        pinched=finite & valid & explained.any(axis=1),
        collapsed_pillars=collapsed.sum(axis=1),
        valid=valid,
        vertex=vertex,
    )


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

        missing = missing_properties(obj)
        for name in missing:
            writer.writerow(
                dict(
                    severity="WARNING",
                    code="missing_property:" + name,
                    i="",
                    j="",
                    k="",
                    cell_id="",
                    region="",
                )
            )
        for start, data, order in iterate(obj):
            progress.report(start / cells, "model_qc geometry/property scan")
            active = data["active"].astype(bool)
            active_all[start : start + len(active)] = active
            ids = ijk(np.arange(start, start + len(active)), shape, order)
            regions = region(data, p["region_field"])
            flags = geometry_flags(data["corners"], obj["summary"].get("storage"))
            finite, safe, volume = flags["finite"], flags["safe"], flags["volume"]
            issue(active & ~finite, "ERROR", "nonfinite_geometry", start, ids, regions)
            reference = integral(safe)
            independent_ok &= bool(np.allclose(volume, reference, rtol=1e-10, atol=1e-8))
            checked += len(active)
            issue(active & flags["negative"], "ERROR", "negative_signed_volume", start, ids, regions)
            issue(active & flags["twisted"], "ERROR", "twisted_cell", start, ids, regions)
            issue(active & flags["degenerate"], "ERROR", "degenerate_cell", start, ids, regions)
            # Valid corner-point pinch-out: zero-length pillar(s), positive volume, no negative Jacobian.
            issue(active & flags["pinched"], "INFO", "pinched_pillar_cell", start, ids, regions)
            for name in ("phi", "ntg", "sw", "permeability_md", "kz_ratio"):
                if name in missing:
                    # An absent array is not a range violation; reported once below as missing_property.
                    continue
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
    review_only = {"ntg_zero_with_porosity", "small_isolated_clusters", "pinched_pillar_cell"}
    return dict(
        operation="model_qc",
        status="ISSUES" if any(v for k, v in counts.items() if k not in review_only) else "PASS",
        missing_properties=[
            dict(
                property=name,
                source_keyword=SOURCE_KEYWORDS.get(name),
                severity="WARNING",
                code="missing_property:" + name,
                note="Array absent from the model; not a range violation. Supply an explicit user value "
                "(e.g. sw_override) where a calculation needs it; nothing is inferred.",
            )
            for name in missing
        ],
        severity_definitions=dict(
            ERROR="Cell-level numerical defect",
            WARNING="Review item or absent property",
            INFO="pinched_pillar_cell: corner-point pinch-out with zero-length pillar(s), positive volume "
            "and no negative Jacobian; valid for volumetrics",
        ),
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
