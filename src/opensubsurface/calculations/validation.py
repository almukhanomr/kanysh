"""Independent static checks. Does not call production volumes/quantiles/import functions."""

import json
import math
import zipfile

import numpy as np
import pyarrow.parquet as pq

from opensubsurface.errors import DomainError
from opensubsurface.persistence.store import digest, file_hash

PROFILE = "static-qc-v1"
RTOL, ATOL = 1e-8, 1e-7


def reference_chunked(obj, cases):
    """Independent interval-overlap integral + Neumaier sums; shared storage reader only."""
    if obj["summary"].get("storage") == "cornerpoint-zarr-v1":
        from opensubsurface.calculations.cornerpoint_reference import reference

        return reference(obj, cases)
    from opensubsurface.adapters.large_grid import blocks, open_grid

    grid = obj["summary"]["grid"]
    nx, ny, nz = grid["shape"]
    xmin, xmax, ymin, ymax, zmin, zmax = grid["extent"]
    area, dz = (xmax - xmin) * (ymax - ymin) / (nx * ny), (zmax - zmin) / nz
    names = ("GRV", "GRV_oil_interval", "NetRockVolume", "PV", "HCPV")
    totals = [[0.0] * 5 for _ in cases]
    corrections = [[0.0] * 5 for _ in cases]
    counts = [0] * len(cases)
    with open_grid(obj) as group:
        for start, data in blocks(group):
            indices = np.arange(start, start + len(data["active"]), dtype=np.int64)
            layer = nz - 1 - indices // (nx * ny) if group.attrs["order"] == "ECLIPSE" else indices % nz
            bottom = zmin + layer * dz
            for i, case in enumerate(cases):
                mask = (data["active"] != 0) & np.isin(data["zones"], case["zone_ids"])
                count = int(mask.sum())
                counts[i] += count
                thickness = np.maximum(
                    0, np.minimum(dz, bottom[mask] + dz - np.maximum(bottom[mask], case["contact_z_m"]))
                )
                override = case.get("overrides", {})
                phi, ntg, sw = [override.get(k, data[k][mask]) for k in ("phi", "ntg", "sw")]
                net = area * thickness * ntg
                pore = net * phi
                values = [
                    count * area * dz,
                    float(np.sum(area * thickness, dtype=np.float64)),
                    float(np.sum(net, dtype=np.float64)),
                    float(np.sum(pore, dtype=np.float64)),
                    float(np.sum(pore * (1 - sw), dtype=np.float64)),
                ]
                for j, value in enumerate(values):
                    previous = totals[i][j]
                    updated = previous + value
                    corrections[i][j] += (
                        (previous - updated) + value
                        if abs(previous) >= abs(value)
                        else (value - updated) + previous
                    )
                    totals[i][j] = updated
    result = []
    for i, case in enumerate(cases):
        if not counts[i]:
            raise ValueError("No active selected cells")
        values = dict(zip(names, [math.fsum([a, b]) for a, b in zip(totals[i], corrections[i])]))
        values["STOIIP"] = values["HCPV"] / case["bo"]
        result.append(values)
    return result


def reference_volumes(arrays, grid, zone_ids, contact, bo, overrides=None):
    """Layer interval intersections, independent of production center-grid/fraction kernel."""
    overrides = overrides or {}
    nx, ny, nz = grid["shape"]
    xmin, xmax, ymin, ymax, zmin, zmax = grid["extent"]
    area, dz = (xmax - xmin) * (ymax - ymin) / (nx * ny), (zmax - zmin) / nz
    selected = arrays["active"].astype(bool) & np.isin(arrays["zones"], zone_ids)
    total = {key: [] for key in ("GRV", "GRV_oil_interval", "NetRockVolume", "PV", "HCPV")}
    for k in range(nz):
        mask = selected[:, :, k]
        bottom, top = zmin + k * dz, zmin + (k + 1) * dz
        thickness = max(0.0, top - max(bottom, contact))
        total["GRV"].append(int(mask.sum()) * area * dz)
        total["GRV_oil_interval"].append(int(mask.sum()) * area * thickness)
        values = {
            name: (
                np.full(int(mask.sum()), overrides[name])
                if name in overrides
                else arrays[name][:, :, k][mask]
            )
            for name in ("phi", "ntg", "sw")
        }
        net = values["ntg"] * area * thickness
        pore = net * values["phi"]
        hydrocarbon = pore * (1.0 - values["sw"])
        for key, vector in (("NetRockVolume", net), ("PV", pore), ("HCPV", hydrocarbon)):
            total[key].append(float(np.sum(vector, dtype=np.float64)))
    result = {name: math.fsum(layers) for name, layers in total.items()}
    result["STOIIP"] = result["HCPV"] / bo
    return result


def statistics(values):
    v = sorted(map(float, values))

    def q(fraction):
        position = (len(v) - 1) * fraction
        left = math.floor(position)
        return v[left] + (position - left) * (v[math.ceil(position)] - v[left])

    mean = math.fsum(v) / len(v)
    return dict(
        min=v[0],
        max=v[-1],
        mean=mean,
        std=math.sqrt(math.fsum((x - mean) ** 2 for x in v) / len(v)),
        Q10=q(0.1),
        Q50=q(0.5),
        Q90=q(0.9),
        P90=q(0.1),
        P50=q(0.5),
        P10=q(0.9),
    )


def check_artifact(obj, related):
    checks = []

    def check(name, ok, observed=None, expected=None, required=True, note=None):
        checks.append(
            dict(
                id=name,
                status="PASS" if ok else "FAIL",
                required=required,
                observed=observed,
                expected=expected,
                note=note,
            )
        )

    def skipped(name, reason, required=True):
        checks.append(dict(id=name, status="NOT RUN", required=required, note=reason))

    def close(name, actual, expected):
        finite = isinstance(actual, (float, int)) and math.isfinite(actual)
        expected_finite = math.isfinite(expected)
        check(
            name,
            finite and expected_finite and math.isclose(actual, expected, rel_tol=RTOL, abs_tol=ATOL),
            actual if finite else None,
            expected if expected_finite else None,
            note=f"rtol={RTOL}, atol={ATOL}",
        )

    def arrays(target):
        with np.load(target["paths"]["arrays.npz"], allow_pickle=False) as data:
            return {key: data[key] for key in data.files}

    try:
        targets = {obj["id"]: obj, **{v["id"]: v for v in related.values()}}
        intact = True
        for target in targets.values():
            manifest = {k: v for k, v in target.items() if k not in ("paths", "content_hash")}
            ok = digest(manifest) == target["content_hash"] and all(
                file_hash(target["paths"][name]) == value for name, value in target["files"].items()
            )
            check("integrity:" + target["id"], ok)
            intact &= ok
        if not intact:
            skipped("numerical_checks", "Input integrity failed")
        elif obj["kind"] == "dataset":
            table = pq.read_table(obj["paths"]["data.parquet"])
            check(
                "dataset.rows",
                table.num_rows > 0 and table.num_rows == obj["summary"]["rows"],
                table.num_rows,
            )
            numeric = [name for name in table.column_names if name not in ("well_id", "horizon", "date")]
            for name in numeric:
                values = np.asarray(table[name].to_numpy(), dtype=float)
                # LAS nulls are valid missing observations; other declared input tables require finite values.
                ok = (
                    not np.isinf(values).any()
                    if obj["summary"]["kind"] == "las"
                    else np.isfinite(values).all()
                )
                check("dataset.finite:" + name, bool(ok), dict(missing=int(np.isnan(values).sum())))
                if name in ("x", "y", "z", "md", "reference_elevation"):
                    check("dataset.units:" + name, obj["summary"]["units"].get(name) == "m")
            if obj["summary"]["kind"] == "orientations":
                normals = np.array([table[name].to_numpy() for name in ("nx", "ny", "nz")], float)
                check(
                    "orientations.unit_normals", bool(np.all(np.abs(np.sum(normals**2, axis=0) - 1) <= 2e-5))
                )
            check(
                "dataset.coordinates_declared",
                bool(obj["summary"].get("crs")) and bool(obj["summary"].get("vertical_datum")),
            )
        elif obj["kind"] == "properties" and obj["summary"].get("storage") in (
            "cartesian-zarr-flat-v1",
            "cornerpoint-zarr-v1",
        ):
            from opensubsurface.adapters.large_grid import UNITS, blocks, open_grid

            invalid, active_count, zone_ids = set(), 0, set()
            with open_grid(obj) as group:
                for _, data in blocks(group):
                    active = data["active"].astype(bool)
                    active_count += int(active.sum())
                    if "corners" in data:
                        from opensubsurface.calculations.cornerpoint_reference import integral

                        corners = data["corners"][active]
                        if not np.isfinite(corners).all() or not (integral(corners) > 0).all():
                            invalid.add("geometry")
                    if not np.all((data["active"] == 0) | (data["active"] == 1)):
                        invalid.add("active")
                    zone_ids.update(map(int, np.unique(data["zones"][active])))
                    if not np.all(data["zones"][active] >= 1) or len(zone_ids) > 10000:
                        invalid.add("zones")
                    for name in ("phi", "ntg", "sw", "permeability_md", "kz_ratio"):
                        v = data[name][active]
                        valid = np.isfinite(v) & (v >= 0)
                        if name != "permeability_md":
                            valid &= v <= 1
                        if name == "kz_ratio":
                            valid &= v > 0
                        if not valid.all():
                            invalid.add(name)
            check("chunked.physical_bounds", not invalid, sorted(invalid))
            check(
                "chunked.active_cells",
                active_count > 0 and active_count == obj["summary"]["active_cells"],
                active_count,
            )
            check("chunked.zone_ids", sorted(zone_ids) == obj["summary"]["zone_ids"])
            check(
                "chunked.units_and_coordinates",
                obj["summary"]["units"] == UNITS
                and bool(obj["summary"].get("crs"))
                and bool(obj["summary"].get("vertical_datum")),
            )
            check(
                "chunked.input_hashes",
                (
                    bool(obj["summary"]["source_sha256"])
                    if obj["summary"].get("source_format") == "opensubsurface.eclipse.static.v1"
                    else set(obj["summary"]["source_sha256"])
                    == (
                        (set(UNITS) - {"active"}) | {"geometry"}
                        if obj["summary"]["storage"] == "cornerpoint-zarr-v1"
                        else set(UNITS)
                    )
                )
                and all(len(h) == 64 for h in obj["summary"]["source_sha256"].values()),
            )
        elif obj["kind"] in ("model", "properties"):
            data = arrays(obj)
            grid = obj["summary"]["grid"]
            shape = tuple(grid["shape"])
            check("grid.shape", all(a.shape == shape for a in data.values()))
            active = data["active"].astype(bool)
            check("grid.active", bool(active.any()), int(active.sum()))
            check("grid.zone_ids", bool(np.all(data["zones"][active] >= 1)))
            extent = grid["extent"]
            check(
                "grid.extent",
                len(extent) == 6
                and all(math.isfinite(x) for x in extent)
                and all(extent[2 * i] < extent[2 * i + 1] for i in range(3)),
            )
            if obj["kind"] == "model" and obj["parameters"].get("method") == "horizontal_explicit":
                dz = (extent[5] - extent[4]) / shape[2]
                expected = [
                    1 + sum(extent[4] + (k + 0.5) * dz >= h for h in obj["parameters"]["horizons_z"])
                    for k in range(shape[2])
                ]
                check(
                    "model.horizontal_zones",
                    bool(np.all(data["zones"] == np.asarray(expected)[None, None, :])),
                )
            elif obj["kind"] == "model":
                skipped(
                    "model.geological_boundary_accuracy",
                    "Requires observed horizon fit/convergence assessment",
                    required=False,
                )
            if obj["kind"] == "properties":
                for name, low, high in (
                    ("phi", 0, 1),
                    ("ntg", 0, 1),
                    ("sw", 0, 1),
                    ("permeability_md", 0, float("inf")),
                    ("kz_ratio", 0, 1),
                ):
                    values = data[name][active]
                    check(
                        "properties.bounds:" + name,
                        bool(np.all(np.isfinite(values) & (values >= low) & (values <= high))),
                    )
                model = related.get("model")
                if model:
                    base = arrays(model)
                    check("properties.model_grid", grid == model["summary"]["grid"])
                    check(
                        "properties.model_mapping",
                        np.array_equal(data["zones"], base["zones"])
                        and np.array_equal(data["active"], base["active"]),
                    )
                else:
                    skipped("properties.model_mapping", "Missing pinned model input")
                for zone, declaration in obj["parameters"].get("zones", {}).items():
                    mask = active & (data["zones"] == int(zone))
                    for name, value in declaration.items():
                        check(
                            f"properties.declaration:{zone}:{name}", bool(np.all(data[name][mask] == value))
                        )
        elif obj["kind"] in ("volumetrics", "scenarios"):
            props = related.get("properties")
            if props is None:
                skipped("independent_volumes", "Missing pinned property input")
            else:
                large = props["summary"].get("storage") in ("cartesian-zarr-flat-v1", "cornerpoint-zarr-v1")
                data = None if large else arrays(props)
                p, grid = obj["parameters"], props["summary"]["grid"]
                if obj["kind"] == "volumetrics":
                    expected = (
                        reference_chunked(props, [p])[0]
                        if large
                        else reference_volumes(data, grid, p["zone_ids"], p["contact_z_m"], p["bo"])
                    )
                    serialized = json.loads(open(obj["paths"]["result.json"]).read())
                    for metric, value in expected.items():
                        close("volumes:" + metric, obj["summary"]["values"].get(metric), value)
                        close("serialized:" + metric, serialized["values"].get(metric), value)
                        check(
                            "units:" + metric,
                            obj["summary"]["units"].get(metric)
                            == ("standard_m3" if metric == "STOIIP" else "m3"),
                        )
                else:
                    rows = json.loads(open(obj["paths"]["samples.json"]).read())
                    check(
                        "samples.count",
                        len(rows) == p["count"] == obj["summary"]["count"] and len(rows) > 0,
                        len(rows),
                    )
                    rng = np.random.default_rng(p["seed"])
                    samples = {}
                    for name, distribution in p["distributions"].items():
                        if distribution["kind"] == "constant":
                            values = np.repeat(distribution["low"], p["count"])
                        elif distribution["kind"] == "uniform":
                            values = rng.uniform(distribution["low"], distribution["high"], p["count"])
                        else:
                            values = rng.triangular(
                                distribution["low"], distribution["mode"], distribution["high"], p["count"]
                            )
                        samples[name] = values
                    valid_rows, metrics = True, []
                    if large:
                        cases = []
                        for i in range(p["count"]):
                            override = {name: float(values[i]) for name, values in samples.items()}
                            cases.append(
                                dict(
                                    zone_ids=p["zone_ids"],
                                    contact_z_m=override.get("contact_z_m", p["contact_z_m"]),
                                    bo=override.get("bo", p["bo"]),
                                    overrides=override,
                                )
                            )
                        references = reference_chunked(props, cases)
                    for i, row in enumerate(rows):
                        if i >= p["count"]:
                            valid_rows = False
                            break
                        override = {name: float(values[i]) for name, values in samples.items()}
                        expected = (
                            references[i]
                            if large
                            else reference_volumes(
                                data,
                                grid,
                                p["zone_ids"],
                                override.get("contact_z_m", p["contact_z_m"]),
                                override.get("bo", p["bo"]),
                                override,
                            )
                        )
                        valid_rows &= (
                            row["seed"] == p["seed"]
                            and row["realization"] == i
                            and row["parameters"] == override
                        )
                        valid_rows &= all(
                            math.isclose(row["result"][k], v, rel_tol=RTOL, abs_tol=ATOL)
                            for k, v in expected.items()
                        )
                        metrics.append(expected["STOIIP"])
                    check("samples.seed_parameters_and_all_metrics", bool(valid_rows))
                    if metrics:
                        for metric, value in statistics(metrics).items():
                            close("statistics:" + metric, obj["summary"]["statistics"].get(metric), value)
        else:
            skipped("supported_profile", "Validator does not support artifact kind " + obj["kind"])
    except (
        DomainError,
        KeyError,
        ValueError,
        TypeError,
        OSError,
        IndexError,
        ZeroDivisionError,
        zipfile.BadZipFile,
    ) as error:
        check("validation.execution", False, note="Malformed/unsupported input: " + type(error).__name__)
    skipped(
        "geological_fitness", "Requires specialist assessment of assumptions and observations", required=False
    )
    required = [c for c in checks if c["required"]]
    status = (
        "FAIL"
        if any(c["status"] == "FAIL" for c in required)
        else ("PASS" if required and all(c["status"] == "PASS" for c in required) else "INCOMPLETE")
    )
    return dict(
        profile=PROFILE,
        status=status,
        checks=checks,
        target=dict(id=obj["id"], revision=obj["revision"], content_hash=obj["content_hash"]),
        tolerances=dict(rtol=RTOL, atol=ATOL),
        geological_fitness="REQUIRES_REVIEW",
        methodology="Independent layer-interval integration; no call to production volume/quantile kernel",
    )
