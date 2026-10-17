"""LAS versus model sampling using explicit surveys, units and tetrahedral point location."""

import csv
import math

import numpy as np
import pyarrow.parquet as pq

from opensubsurface.adapters.cornerpoint import TETS
from opensubsurface.adapters.model_arrays import ijk, iterate, provenance, region
from opensubsurface.errors import require


def inside(corners, point, reference=False):
    found = np.zeros(len(corners), bool)
    for tet in TETS:
        v = corners[:, tet]
        matrix = np.transpose(v[:, 1:] - v[:, :1], (0, 2, 1))
        det = np.linalg.det(matrix)
        scale = np.max(np.abs(matrix), axis=(1, 2)) ** 3
        good = np.isfinite(det) & (
            np.abs(det) > np.finfo(float).eps * 256 * np.maximum(scale, np.finfo(float).tiny)
        )
        if not good.any():
            continue
        a = matrix[good]
        rhs = point - v[good, 0]
        if reference:
            weights = []
            for col in range(3):
                replaced = a.copy()
                replaced[:, :, col] = rhs
                weights.append(np.linalg.det(replaced) / det[good])
            bary = np.stack(weights, axis=1)
        else:
            bary = np.linalg.solve(a, rhs[..., None])[..., 0]
        valid = (bary >= -1e-10).all(axis=1) & (bary.sum(axis=1) <= 1 + 1e-10)
        found[np.flatnonzero(good)[valid]] = True
    return found


def run(obj, trajectory, logs, p, out):
    require(trajectory["summary"].get("kind") == "trajectory", "TYPE_MISMATCH", "Survey trajectory required")
    survey = pq.read_table(trajectory["paths"]["data.parquet"]).to_pandas()
    samples, metadata = [], []
    for descriptor, artifact in zip(p["logs"], logs):
        require(artifact["summary"].get("kind") == "las", "TYPE_MISMATCH", "Original LAS dataset required")
        well = artifact["summary"]["well_id"]
        t = survey[survey["well_id"] == well].sort_values("md")
        require(
            len(t) >= 2 and (np.diff(t.md) > 0).all(),
            "MISSING_TRAJECTORY",
            "No strictly increasing survey for well " + well,
        )
        table = pq.read_table(artifact["paths"]["data.parquet"]).to_pandas()
        curve = descriptor["md_curve"]
        require(
            curve in table and artifact["summary"]["units"].get(curve) == "m",
            "INVALID_UNITS",
            "LAS MD must reference imported canonical meter curve",
        )
        require(
            set(descriptor["property_curves"].values()) <= set(table),
            "MISSING_CURVE",
            "Mapped LAS property curve missing",
        )
        require(
            np.isfinite(table[curve]).all() and (np.diff(table[curve]) > 0).all(),
            "INVALID_LAS",
            "LAS MD must strictly increase",
        )
        md = np.asarray(table[curve])
        for index in range(0, len(table), p["sample_every_n"]):
            depth = float(md[index])
            row = dict(well_id=well, md_m=depth, point=None, values={}, reason=None)
            if depth < t.md.min() or depth > t.md.max():
                row["reason"] = "outside_survey"
            else:
                right = int(np.searchsorted(t.md, depth, side="left"))
                left = max(0, right - 1)
                if right == len(t):
                    right = len(t) - 1
                # At an exact survey station interpolation does not cross the gap.
                exact = bool(np.any(np.asarray(t.md) == depth))
                if not exact and float(t.md.iloc[right] - t.md.iloc[left]) > p["max_survey_gap_m"]:
                    row["reason"] = "survey_gap_exceeds_user_limit"
                else:
                    row["point"] = np.array([np.interp(depth, t.md, t[k]) for k in ("x", "y", "z")])
            for field, name in descriptor["property_curves"].items():
                value = float(table[name].iloc[index])
                factor = 0.01 if descriptor["property_units"][field] == "percent" else 1.0
                row["values"][field] = value * factor if np.isfinite(value) else None
            samples.append(row)
            require(
                len(samples) <= 500000,
                "UNSUPPORTED_PROFILE",
                "LAS comparison limit 500k selected samples; choose explicit sample_every_n",
            )
        metadata.append(
            dict(
                artifact=provenance(artifact),
                well_id=well,
                source_units=artifact["summary"]["units"],
                explicit_mapping=descriptor,
                input_samples=len(table),
                selected_samples=len(range(0, len(table), p["sample_every_n"])),
            )
        )
    require(bool(samples), "INVALID_LAS", "No LAS samples")
    positions = np.array([row["point"] if row["point"] is not None else [np.nan] * 3 for row in samples])
    keys = np.full(len(samples), np.iinfo(np.int64).max, np.int64)
    matches = np.zeros(len(samples), np.int32)
    assignments = [None] * len(samples)
    shape = obj["summary"]["grid"]["shape"]
    independent = True
    for start, data, order in iterate(obj):
        active = data["active"].astype(bool)
        c = data["corners"]
        valid = active & np.isfinite(c).all(axis=(1, 2))
        if not valid.any():
            continue
        rids = region(data, p["region_field"])
        low, high = c.min(axis=1), c.max(axis=1)
        coarse_low, coarse_high = low[valid].min(axis=0), high[valid].max(axis=0)
        candidate_points = np.flatnonzero(
            ((positions >= coarse_low) & (positions <= coarse_high)).all(axis=1)
        )
        for index in candidate_points:
            point = positions[index]
            candidates = np.flatnonzero(valid & ((point >= low) & (point <= high)).all(axis=1))
            if not len(candidates):
                continue
            located = candidates[inside(c[candidates], point)]
            if not len(located):
                continue
            independent &= bool(inside(c[located], point, reference=True).all())
            matches[index] += len(located)
            physical = ijk(start + located, shape, order)
            physical_keys = np.ravel_multi_index(physical.T, shape, order="C")
            best = int(np.argmin(physical_keys))
            local = int(located[best])
            if physical_keys[best] < keys[index]:
                keys[index] = physical_keys[best]
                assignments[index] = dict(
                    cell_id=int(start + local),
                    ijk=(physical[best] + 1).tolist(),
                    region_id=int(rids[local]),
                    values={field: float(data[field][local]) for field in ("phi", "ntg")},
                )
    groups, excluded, examples = {}, {}, []
    with (out / "well_samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "well_id",
                "md_m",
                "region_id",
                "cell_id",
                "i",
                "j",
                "k",
                "property",
                "las",
                "model",
                "error",
                "status",
            ],
        )
        writer.writeheader()
        for index, (sample, assignment) in enumerate(zip(samples, assignments)):
            reason = sample["reason"] or ("outside_model" if assignment is None else None)
            if matches[index] > 1 and p["boundary_policy"] == "reject":
                reason = "multiple_cells_or_boundary"
            for field, value in sample["values"].items():
                status = reason or ("LAS_null" if value is None else None)
                actual = assignment["values"][field] if assignment is not None else None
                if not status and (
                    actual is None or not np.isfinite(actual) or not 0 <= actual <= 1 or not 0 <= value <= 1
                ):
                    status = "invalid_property_range"
                row = dict(
                    well_id=sample["well_id"],
                    md_m=sample["md_m"],
                    property=field,
                    las=value,
                    model=actual if actual is not None and np.isfinite(actual) else None,
                    status=status or "compared",
                )
                if assignment:
                    row.update(
                        region_id=assignment["region_id"],
                        cell_id=assignment["cell_id"],
                        i=assignment["ijk"][0],
                        j=assignment["ijk"][1],
                        k=assignment["ijk"][2],
                    )
                if status:
                    excluded[status] = excluded.get(status, 0) + 1
                else:
                    error = actual - value
                    row["error"] = error
                    groups.setdefault((sample["well_id"], assignment["region_id"], field), []).append(
                        (value, actual, error)
                    )
                writer.writerow(row)
                if len(examples) < 100:
                    examples.append(row)
    rows = []
    for (well, rid, field), values in sorted(groups.items()):
        a = np.asarray(values)
        error = a[:, 2]
        rmse = float(np.sqrt(np.mean(error**2)))
        reference_rmse = math.sqrt(math.fsum(float(v) * float(v) for v in error) / len(error))
        independent &= math.isclose(rmse, reference_rmse, rel_tol=1e-12, abs_tol=1e-12)
        rows.append(
            dict(
                well_id=well,
                region_id=rid,
                property=field,
                n=len(error),
                bias_model_minus_LAS=float(error.mean()),
                MAE=float(np.mean(np.abs(error))),
                RMSE=rmse,
                correlation=float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])
                if len(error) > 1 and np.std(a[:, 0]) > 0 and np.std(a[:, 1]) > 0
                else None,
            )
        )
    status = "PASS" if independent and rows else "NOT RUN" if not rows else "FAIL"
    return dict(
        operation="wells_vs_model",
        status="COMPLETE" if rows and not excluded else "PARTIAL" if rows else "NO_COMPARABLE_SAMPLES",
        validation_status=status,
        scope="Point-sampled model PORO/NTG versus explicitly mapped original LAS; no automatic log upscaling or calibration",
        input=provenance(obj),
        trajectory=provenance(trajectory),
        logs=metadata,
        parameters=p,
        assumptions=p["assumptions"],
        tables=dict(wells_zones=rows),
        examples=examples,
        excluded=excluded,
        boundary_samples=int((matches > 1).sum()),
        independent_checks=[
            dict(name="point_containment_solve_vs_Cramer", status=status),
            dict(name="RMSE_numpy_vs_scalar_fsum", status=status),
        ],
        limitations=[
            "Survey coordinates use linear interpolation in MD; gaps above explicit user limit and extrapolation are excluded",
            "A cell is the union of the declared six tetrahedra; boundary/overlap handling is explicit",
            "Statistics compare point samples; they do not establish geological validity or prescribe property changes",
        ],
    )
