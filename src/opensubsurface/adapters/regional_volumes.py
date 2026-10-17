"""Regional oil/free-gas volumetrics with explicit user parameters and independent integrals."""

import math

import numpy as np
import pyarrow.parquet as pq

from opensubsurface.adapters.cornerpoint import cell_volumes
from opensubsurface.adapters.model_arrays import iterate, provenance, region
from opensubsurface.calculations.cornerpoint_reference import integral
from opensubsurface.errors import require

METRIC_DEFINITIONS = dict(
    GRV="Full active selected region bulk volume m3",
    GRV_oil_interval="Bulk above OWC and below GOC when provided, m3",
    NetRockVolume="Oil interval bulk times NTG, m3",
    PV="Oil interval net pore volume, m3",
    HCPV="Oil interval pore volume times (1-Sw-Sg_oil), m3",
    STOIIP="Initial oil HCPV/Bo, standard m3; not recoverable reserves",
    TotalPV="Whole selected region net pore volume, m3",
    GasGRV="Bulk above GOC, m3",
    GasPV="Gas interval net pore volume, m3",
    GasHCPV="Gas interval pore volume times (1-Sw-So_gas), m3",
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
    rows = []
    indices = {}
    accumulators = {}
    reference = {}
    counts = {}
    for s, scenario in enumerate(p["scenarios"]):
        for case in scenario["regions"]:
            key = (s, case["region_id"])
            indices[key] = case
            accumulators[key] = [[] for _ in range(10)]
            reference[key] = [[] for _ in range(10)]
            counts[key] = 0
    selected_by_polygon = 0
    for _, data, _ in iterate(obj):
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
        for key, case in indices.items():
            mask = active & (regions == case["region_id"])
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
            require(
                np.isfinite(c).all()
                and all(np.isfinite(v).all() and (v >= 0).all() and (v <= 1).all() for v in (phi, ntg, sw)),
                "INVALID_PROPERTY",
                "Nonfinite/out-of-range active geometry, phi, NTG or Sw; use model_qc",
            )
            from opensubsurface.adapters.model_qc import jacobians

            orientation = -1 if obj["summary"].get("storage") == "cornerpoint-zarr-v1" else 1
            determinants = jacobians(c) * orientation
            scale = np.max(np.ptp(c, axis=1), axis=1) ** 3
            require(
                (
                    determinants.min(axis=1)
                    > np.finfo(float).eps * 256 * np.maximum(scale, np.finfo(float).tiny)
                ).all(),
                "INVALID_GEOMETRY",
                "Selected model has degenerate/inverted/twisted cells; inspect model_qc before volumetrics",
            )
            oil_fraction = 1 - sw - case["oil_gas_saturation"]
            gas_fraction = (
                1 - sw - case["gas_oil_saturation"] if case.get("goc_z_m") is not None else np.zeros(len(c))
            )
            require(
                (oil_fraction >= 0).all() and (gas_fraction >= 0).all(),
                "INVALID_SATURATION",
                "User saturations exceed unity",
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
            counts[key] > 0, "EMPTY_REGION", "No active cells selected for region " + str(case["region_id"])
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
    return dict(
        operation="regional_volumes",
        status="PASS",
        validation_status="PASS" if independent else "NOT RUN",
        scope="Static initial oil and free gas, not recoverable reserves or production forecast",
        input=provenance(obj),
        region_field=p["region_field"],
        parameters=p,
        assumptions=p["assumptions"],
        tables=dict(regions=rows, scenarios=totals),
        metric_definitions=METRIC_DEFINITIONS,
        independent_checks=checks,
        limitations=[
            "Six-tetrahedron cell geometry convention; Z is positive upward",
            "Saturation-height functions are evaluated at the mean corner height of each selected cell",
            "Polygon selection, when requested, keeps whole cells by mean corner XY; no polygon fractional clipping",
            "Free-gas GIIP excludes dissolved gas; all residual phase saturations and Bo/Bg are explicit user inputs",
        ],
    )
