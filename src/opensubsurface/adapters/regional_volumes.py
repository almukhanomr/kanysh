"""Regional oil/free-gas volumetrics with explicit user parameters and independent integrals."""

import math

import numpy as np
import pyarrow.parquet as pq

from opensubsurface.adapters.cornerpoint import cell_volumes
from opensubsurface.adapters.model_arrays import ijk, iterate, provenance, region
from opensubsurface.calculations.cornerpoint_reference import integral
from opensubsurface.errors import DomainError, require

METRIC_DEFINITIONS = dict(
    GRV="Full active selected region bulk volume m3",
    GRV_oil_interval="Bulk above OWC and below GOC when provided, m3",
    NetRockVolume="Oil interval bulk times NTG, m3",
    PV="Oil interval net pore volume, m3",
    HCPV="Oil interval pore volume times (1-Sw-sg_in_oil_zone), m3",
    STOIIP="Initial oil HCPV/Bo, standard m3; not recoverable reserves",
    TotalPV="Whole selected region net pore volume, m3",
    GasGRV="Bulk above GOC, m3",
    GasPV="Gas interval net pore volume, m3",
    GasHCPV="Gas interval pore volume times (1-Sw-so_in_gas_zone), m3",
    GIIP="Free-gas GasHCPV/Bg, standard m3; excludes dissolved gas",
)


def polygon_geometry(obj, p):
    from shapely import Polygon, difference, union_all

    table = pq.read_table(obj["paths"]["data.parquet"]).to_pandas()
    require(obj["summary"].get("kind") == "polygons", "TYPE_MISMATCH", "Polygon artifact required")
    rings = {
        str(key): Polygon(rows[["x", "y"]].to_numpy(float))
        for key, rows in table.groupby("polygon_id", sort=False)
    }
    require(
        set(p["polygon_ids"] + p["polygon_hole_ids"]) <= rings.keys(),
        "MISSING_POLYGON",
        "Selected polygon ring missing",
    )
    require(
        all(g.is_valid and not g.is_empty and g.area > 0 for g in rings.values()),
        "INVALID_POLYGON",
        "Invalid/self-intersecting polygon ring",
    )
    geom = union_all([rings[k] for k in p["polygon_ids"]])
    if p["polygon_hole_ids"]:
        holes = union_all([rings[k] for k in p["polygon_hole_ids"]])
        require(geom.covers(holes), "INVALID_POLYGON", "Hole outside selected exteriors")
        geom = difference(geom, holes)
    return geom


def water_saturation(data, corners, case):
    if case.get("sw_override") is not None:
        return np.full(len(corners), case["sw_override"])
    model = case.get("sw_height")
    if model is None:
        return np.asarray(data["sw"])
    height = np.maximum(corners[:, :, 2].mean(axis=1) - case["owc_z_m"], 0)
    curve = np.asarray(model["table"], float)
    if model["method"] == "table":
        x, y = curve[:, 0], curve[:, 1]
        argument = height
    else:
        phi = (
            np.full(len(corners), case["phi_override"])
            if case.get("phi_override") is not None
            else np.asarray(data["phi"])
        )
        if case.get("phi_multiplier") is not None:
            phi = phi * case["phi_multiplier"]
        permeability = np.asarray(data["permeability_md"]) * 9.869233e-16
        require(
            np.isfinite(permeability).all() and (permeability > 0).all() and (phi > 0).all(),
            "INVALID_PROPERTY",
            "Leverett J requires positive finite permeability and porosity",
        )
        pc = model["density_difference_kg_m3"] * model["gravity_m_s2"] * height
        argument = (
            pc
            * np.sqrt(permeability / phi)
            / (model["surface_tension_mN_m"] * 0.001 * math.cos(math.radians(model["contact_angle_deg"])))
        )
        x, y = curve[::-1, 1], curve[::-1, 0]
    if model["extrapolation"] == "reject":
        require(
            (argument >= x[0]).all() and (argument <= x[-1]).all(),
            "TABLE_RANGE_EXCEEDED",
            "Saturation-height argument outside user table",
        )
    return np.interp(argument, x, y)


def evaluate(obj, p, polygon=None, independent=True):
    from opensubsurface.adapters.model_qc import geometry_flags
    from opensubsurface.execution import progress

    rows = []
    indices = {}
    accumulators = {}
    reference = {}
    counts = {}
    excluded = {}
    policy = p.get("geometry_policy", "strict")
    for s, scenario in enumerate(p["scenarios"]):
        for r, case in enumerate(scenario["regions"]):
            key = (s, case["region_id"])
            indices[key] = case
            accumulators[key] = [[] for _ in range(10)]
            reference[key] = [[] for _ in range(10)]
            counts[key] = 0
            excluded[key] = dict(
                path=f"scenarios[{s}].regions[{r}]", cells=0, GRV_tetra6_m3=[], GRV_bbox_m3=[], PV_bbox_m3=[]
            )
    selected_by_polygon = 0
    witnesses = []
    total_cells = math.prod(obj["summary"]["grid"]["shape"])
    for start, data, _ in iterate(obj):
        progress.report(start / total_cells, "regional volumes")
        active = data["active"].astype(bool)
        regions = region(data, p["region_field"])
        if polygon is not None:
            from shapely import contains_xy, intersects_xy

            center = data["corners"].mean(axis=1)
            selected = (intersects_xy if p["polygon_boundary"] == "include" else contains_xy)(
                polygon, center[:, 0], center[:, 1]
            )
            active &= selected
            selected_by_polygon += int(active.sum())
        flags = None
        for key, case in indices.items():
            mask = active & (regions == case["region_id"])
            if not mask.any():
                continue
            if flags is None:
                flags = geometry_flags(data["corners"], obj["summary"].get("storage"))
            path = excluded[key]["path"]
            invalid = mask & ~flags["valid"]
            if invalid.any():
                local_ids = np.flatnonzero(invalid)
                first = ijk(
                    local_ids[:5] + start, obj["summary"]["grid"]["shape"], obj["summary"].get("order", "C")
                )
                require(
                    policy == "exclude_flagged",
                    "INVALID_GEOMETRY",
                    f"Region {case['region_id']}: at least {len(local_ids)} selected active cells are "
                    f"degenerate/inverted/twisted (first IJK {(first + 1).tolist()}); geometry_policy=strict "
                    "refuses volumetrics on them",
                    "geometry_policy",
                    f"Inspect model_qc of properties {obj['id']} r{obj['revision']} (issues.csv lists every IJK "
                    "witness). If the user confirms excluding flagged cells, resend with "
                    "geometry_policy='exclude_flagged' and parameters_confirmed=true: the excluded count, "
                    "bounding GRV/PV and share are reported and validation_status becomes PASS_WITH_EXCLUSIONS.",
                    dict(region_id=case["region_id"], first_ijk=(first + 1).tolist(), request_path=path),
                )
                bad = data["corners"][invalid]
                bbox = np.prod(np.ptp(bad, axis=1), axis=1)
                record = excluded[key]
                record["cells"] += len(local_ids)
                record["GRV_tetra6_m3"].append(float(np.sum(flags["volume"][invalid])))
                record["GRV_bbox_m3"].append(float(np.sum(bbox)))
                pore = bbox * np.asarray(data["phi"])[invalid] * np.asarray(data["ntg"])[invalid]
                record["PV_bbox_m3"].append(float(np.sum(pore[np.isfinite(pore)])))
                for local in local_ids[: max(0, 1000 - len(witnesses))]:
                    witnesses.append(
                        dict(
                            scenario=p["scenarios"][key[0]]["name"],
                            region_id=case["region_id"],
                            cell_id=int(start + local),
                            ijk=(
                                ijk(
                                    np.array([start + local]),
                                    obj["summary"]["grid"]["shape"],
                                    obj["summary"].get("order", "C"),
                                )[0]
                                + 1
                            ).tolist(),
                            code="twisted_cell"
                            if flags["twisted"][local]
                            else "negative_signed_volume"
                            if flags["negative"][local]
                            else "degenerate_cell",
                            GRV_tetra6_m3=float(flags["volume"][local]),
                        )
                    )
                mask = mask & flags["valid"]
                if not mask.any():
                    continue
            counts[key] += int(mask.sum())
            c = data["corners"][mask]
            subset = {name: v[mask] for name, v in data.items() if name != "corners"}
            phi = (
                np.full(len(c), case["phi_override"])
                if case.get("phi_override") is not None
                else subset["phi"]
            )
            ntg = (
                np.full(len(c), case["ntg_override"])
                if case.get("ntg_override") is not None
                else subset["ntg"]
            )
            if case.get("phi_multiplier") is not None:
                phi = phi * case["phi_multiplier"]
            if case.get("ntg_multiplier") is not None:
                ntg = ntg * case["ntg_multiplier"]
            sw = water_saturation(subset, c, case)
            if case.get("sw_multiplier") is not None:
                sw = sw * case["sw_multiplier"]
            for name, values, fix in (
                ("phi", phi, "phi_override"),
                ("ntg", ntg, "ntg_override"),
                ("sw", sw, "sw_override"),
            ):
                bad = ~(np.isfinite(values) & (values >= 0) & (values <= 1))
                nonfinite = int((~np.isfinite(values)).sum())
                require(
                    not bad.any(),
                    "INVALID_PROPERTY",
                    f"Region {case['region_id']}: {int(bad.sum())} selected cells have "
                    + ("missing/nonfinite " if nonfinite else "out-of-range ")
                    + f"{name} after overrides/multipliers ({nonfinite} nonfinite)",
                    f"{path}.{fix}",
                    f"Run model_qc to locate the cells. If {name} is absent or must be replaced, set {fix}"
                    + (" or sw_height" if name == "sw" else "")
                    + " for this region with user confirmation; multipliers never supply missing values.",
                )
            # Oil interval: Sw + free gas + oil = 1. Gas cap: Sw + residual oil + gas = 1.
            oil_fraction = 1 - sw - case["sg_in_oil_zone"]
            gas_fraction = (
                1 - sw - case["so_in_gas_zone"] if case.get("goc_z_m") is not None else np.zeros(len(c))
            )
            require(
                (oil_fraction >= 0).all(),
                "INVALID_SATURATION",
                f"Region {case['region_id']}: Sw + sg_in_oil_zone exceeds 1",
                path + ".sg_in_oil_zone",
                "Reduce sg_in_oil_zone or Sw so that Sw + Sg <= 1 in the oil interval",
            )
            require(
                (gas_fraction >= 0).all(),
                "INVALID_SATURATION",
                f"Region {case['region_id']}: Sw + so_in_gas_zone exceeds 1",
                path + ".so_in_gas_zone",
                "Reduce so_in_gas_zone or Sw so that Sw + So <= 1 in the gas cap",
            )

            def reduce(volumes):
                whole, above_owc, gas = volumes
                oil = np.maximum(above_owc - gas, 0)
                oil_pore = oil * ntg * phi
                gas_pore = gas * ntg * phi
                return (
                    whole,
                    oil,
                    oil * ntg,
                    oil_pore,
                    oil_pore * oil_fraction,
                    whole * ntg * phi,
                    gas,
                    gas_pore,
                    gas_pore * gas_fraction,
                    np.ones(len(c)),
                )

            whole = cell_volumes(c)
            above = cell_volumes(c, case["owc_z_m"])
            gas = cell_volumes(c, case["goc_z_m"]) if case.get("goc_z_m") is not None else np.zeros(len(c))
            for target, values in zip(accumulators[key], reduce((whole, above, gas))):
                target.append(float(np.sum(values, dtype=np.float64)))
            if independent:
                independent_whole = integral(c)
                independent_above = integral(c, case["owc_z_m"])
                independent_gas = (
                    integral(c, case["goc_z_m"]) if case.get("goc_z_m") is not None else np.zeros(len(c))
                )
                # Reference geometry is computed by independent determinant/hull clipping;
                # scalar products are accumulated separately using math.fsum.
                for target, values in zip(
                    reference[key], reduce((independent_whole, independent_above, independent_gas))
                ):
                    target.append(math.fsum(map(float, values)))
    checks = []
    for key, case in indices.items():
        require(
            counts[key] > 0,
            "EMPTY_REGION",
            "No active valid cells selected for region " + str(case["region_id"]),
            excluded[key]["path"] + ".region_id",
            "Check region_field/region_id against the properties summary region_ids and the polygon selection",
        )
        values = [math.fsum(a) for a in accumulators[key]]
        if independent:
            expected = [math.fsum(a) for a in reference[key]]
            ok = bool(np.allclose(values, expected, rtol=1e-8, atol=1e-7))
            require(ok, "VALIDATION_FAILED", "Independent regional integral mismatch")
            checks.append(
                dict(
                    scenario=p["scenarios"][key[0]]["name"],
                    region_id=key[1],
                    name="independent_determinant_hull_integral",
                    status="PASS",
                    max_absolute_difference=float(np.max(np.abs(np.array(values) - expected))),
                )
            )
        row = dict(
            scenario=p["scenarios"][key[0]]["name"],
            region_id=key[1],
            selected_cells=counts[key],
            owc_z_m=case["owc_z_m"],
            goc_z_m=case.get("goc_z_m"),
            bo=case["bo"],
            bg=case.get("bg"),
            excluded_cells=excluded[key]["cells"],
        )
        for name, value in zip(
            (
                "GRV",
                "GRV_oil_interval",
                "NetRockVolume",
                "PV",
                "HCPV",
                "TotalPV",
                "GasGRV",
                "GasPV",
                "GasHCPV",
            ),
            values,
        ):
            row[name] = value
        row["STOIIP"] = row["HCPV"] / case["bo"]
        row["GIIP"] = row["GasHCPV"] / case["bg"] if case.get("bg") is not None else None
        if case.get("goc_z_m") is None:
            for name in ("GasGRV", "GasPV", "GasHCPV"):
                row[name] = None
        rows.append(row)
    totals = []
    for scenario in p["scenarios"]:
        selected = [row for row in rows if row["scenario"] == scenario["name"]]
        total = dict(scenario=scenario["name"])
        for metric in METRIC_DEFINITIONS:
            values = [row[metric] for row in selected if row.get(metric) is not None]
            total[metric] = math.fsum(values) if values else None
        totals.append(total)
    exclusions = []
    for key, record in excluded.items():
        if not record["cells"]:
            continue
        row = next(
            r for r in rows if r["region_id"] == key[1] and r["scenario"] == p["scenarios"][key[0]]["name"]
        )
        grv, bbox = math.fsum(record["GRV_tetra6_m3"]), math.fsum(record["GRV_bbox_m3"])
        exclusions.append(
            dict(
                scenario=row["scenario"],
                region_id=key[1],
                excluded_cells=record["cells"],
                included_cells=row["selected_cells"],
                excluded_GRV_tetra6_m3=grv,
                excluded_GRV_bbox_m3=bbox,
                excluded_PV_bbox_m3=math.fsum(record["PV_bbox_m3"]),
                share_of_region_GRV_tetra6=grv / (grv + row["GRV"]),
                share_of_region_GRV_bbox_upper=bbox / (bbox + row["GRV"]),
            )
        )
    flagged = bool(exclusions)
    return dict(
        operation="regional_volumes",
        status="PASS_WITH_EXCLUSIONS" if flagged else "PASS",
        validation_status=("PASS_WITH_EXCLUSIONS" if flagged else "PASS") if independent else "NOT RUN",
        scope="Static initial oil and free gas, not recoverable reserves or production forecast",
        input=provenance(obj),
        region_field=p["region_field"],
        parameters=p,
        assumptions=p["assumptions"],
        geometry_policy=policy,
        geometry_exclusions=dict(
            policy=policy,
            excluded_cells=sum(r["excluded_cells"] for r in exclusions),
            note=(
                "Flagged cells (twisted/inverted/degenerate trilinear geometry) are removed from every metric "
                "and from the independent check; bbox values are upper-bound estimates of what was removed. "
                "This is not a clean PASS."
            )
            if flagged
            else "No selected cell was excluded",
        ),
        tables=dict(
            regions=rows,
            scenarios=totals,
            geometry_exclusions=exclusions,
            excluded_cell_witnesses=witnesses,
        ),
        metric_definitions=METRIC_DEFINITIONS,
        independent_checks=checks,
        limitations=[
            "Six-tetrahedron cell geometry convention; Z is positive upward",
            "Saturation-height functions are evaluated at the mean corner height of each selected cell",
            "Polygon selection, when requested, keeps whole cells by mean corner XY; no polygon fractional clipping",
            "Free-gas GIIP excludes dissolved gas; all residual phase saturations and Bo/Bg are explicit user inputs",
            "Corner-point pinch-out cells (zero-length pillars, positive volume, no negative Jacobian) are valid",
        ]
        + (
            ["geometry_policy=exclude_flagged: totals exclude flagged cells (see geometry_exclusions)"]
            if flagged
            else []
        ),
    )


def region_ids(obj, field):
    """Active region ids of field: recorded at import when available, else one bounded array scan."""
    from opensubsurface.adapters.model_arrays import opened

    summary = obj["summary"]
    recorded = (summary.get("region_ids") or {}).get(field)
    if recorded is not None:
        return set(recorded)
    if field == "zones" and summary.get("zone_ids") is not None:
        return set(summary["zone_ids"])
    found = set()
    with opened(obj) as (group, _):
        names = set(group.array_keys()) if hasattr(group, "array_keys") else set(group)
        require(
            field in names,
            "MISSING_REGION",
            f"Region field {field} is absent from properties {obj['id']} r{obj['revision']}",
            "region_field",
            "Choose one of: " + ", ".join(sorted(names & {"zones", "FIPNUM", "EQLNUM", "SATNUM", "PVTNUM"})),
        )
        values, active = group[field], group["active"]
        step = getattr(values, "chunks", (1048576,))[0] or 1048576
        for start in range(0, values.shape[0], max(step, 16384)):
            block = np.asarray(values[start : start + max(step, 16384)])
            mask = np.asarray(active[start : start + max(step, 16384)]).astype(bool)
            found.update(map(int, np.unique(block[mask])))
    return found


def preflight(obj, p):
    """Synchronous checks before a regional job is queued: region ids, properties, contact signs."""
    from opensubsurface.adapters.model_qc import missing_properties

    available = region_ids(obj, p["region_field"])
    missing = set(missing_properties(obj))
    extent = (obj["summary"].get("grid") or {}).get("extent")
    needs = {}
    for s, scenario in enumerate(p["scenarios"]):
        for r, case in enumerate(scenario["regions"]):
            path = f"scenarios[{s}].regions[{r}]"
            require(
                case["region_id"] in available,
                "UNKNOWN_REGION",
                f"region_id {case['region_id']} has no active cells in {p['region_field']} of properties "
                f"{obj['id']} r{obj['revision']}",
                path + ".region_id",
                f"Use one of the active {p['region_field']} ids: "
                + ", ".join(map(str, sorted(available)[:50]))
                + (" ..." if len(available) > 50 else ""),
                dict(available_region_ids=sorted(available)[:1000]),
            )
            height = case.get("sw_height") or {}
            requirements = {
                "phi": case.get("phi_override") is None,
                "ntg": case.get("ntg_override") is None,
                "sw": case.get("sw_override") is None and not case.get("sw_height"),
                "permeability_md": height.get("method") == "leverett_j",
            }
            if height.get("method") == "leverett_j":
                requirements["phi"] = True if case.get("phi_override") is None else requirements["phi"]
            for name, needed in requirements.items():
                if needed and name in missing:
                    needs.setdefault(name, []).append(path)
            if extent:
                low, high = extent[4], extent[5]
                for contact in ("owc_z_m", "goc_z_m"):
                    z = case.get(contact)
                    if z is None:
                        continue
                    # A positive contact whose negation lies inside a below-datum model is a depth sign slip.
                    require(
                        not (z > 0 and high < 0 and low <= -z <= high),
                        "CONTACT_SIGN",
                        f"{contact}={z} is above the model top Z={high:.1f}, while {-z} lies inside the model; "
                        "Z is positive upward",
                        f"{path}.{contact}",
                        f"Confirm with the user: depth {z} m below datum is Z={-z}. Pass {contact}={-z} "
                        "if that is the intended contact.",
                    )
    fixes = dict(
        sw="sw_override or sw_height",
        phi="phi_override",
        ntg="ntg_override",
        permeability_md="(Leverett J needs PERMX; use a method=table sw_height or sw_override)",
    )
    keywords = dict(sw="SWAT", phi="PORO", ntg="NTG", permeability_md="PERMX")
    for name, paths in needs.items():
        total = sum(len(s["regions"]) for s in p["scenarios"])
        field = "sw_override" if name == "sw" else f"{name}_override"
        raise DomainError(
            "MISSING_PROPERTY",
            f"{keywords[name]} is absent from properties {obj['id']} r{obj['revision']} and "
            f"{len(paths)} of {total} region cases do not supply {name}",
            f"scenarios[*].regions[*].{field}" if len(paths) == total else f"{paths[0]}.{field}",
            f"{keywords[name]} is missing in the model; set {fixes[name]} for each listed region with the "
            "user's confirmation (multipliers never supply a missing array). Nothing is inferred.",
            dict(
                missing_property=name, source_keyword=keywords[name], fields=[f"{x}.{field}" for x in paths]
            ),
        )
    return dict(region_ids=sorted(available), missing_properties=sorted(missing))
