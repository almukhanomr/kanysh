import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import zarr

from opensubsurface.adapters.large_grid import UNITS
from opensubsurface.adapters.model_diff import run as model_diff
from opensubsurface.adapters.model_qc import run as model_qc
from opensubsurface.adapters.regional_volumes import evaluate, polygon_geometry
from opensubsurface.adapters.sensitivity import draws, monte_carlo, tornado
from opensubsurface.adapters.volumes_reconcile import run as reconcile
from opensubsurface.adapters.wells_vs_model import run as wells_vs_model
from opensubsurface.errors import DomainError


def model(tmp_path, changes=None, suffix="a"):
    path = tmp_path / ("grid-" + suffix + ".zip")
    offsets = np.array(
        [
            [0, 0, 0],
            [10, 0, 0],
            [0, 10, 0],
            [10, 10, 0],
            [0, 0, -10],
            [10, 0, -10],
            [0, 10, -10],
            [10, 10, -10],
        ]
    )
    centers = np.array([[i * 10, 0, 20 - k * 10] for k in range(2) for i in range(3)])
    arrays = dict(
        corners=(centers[:, None, :] + offsets).astype(float),
        active=np.ones(6, bool),
        zones=np.array([1, 1, 2, 1, 1, 2], np.int32),
        phi=np.full(6, 0.2),
        ntg=np.full(6, 0.8),
        sw=np.full(6, 0.25),
        permeability_md=np.full(6, 100.0),
        kz_ratio=np.full(6, 0.1),
    )
    arrays["FIPNUM"] = arrays["zones"].copy()
    if changes:
        changes(arrays)
    with zarr.ZipStore(str(path), mode="w") as store:
        g = zarr.group(store=store)
        g.attrs.update(storage="cornerpoint-zarr-v1", shape=[3, 1, 2], order="ECLIPSE")
        for k, v in arrays.items():
            g.create_dataset(k, data=v, chunks=(6, 8, 3) if k == "corners" else (6,))
    summary = dict(
        storage="cornerpoint-zarr-v1",
        grid=dict(shape=[3, 1, 2], extent=[0, 30, 0, 10, 0, 20]),
        crs="LOCAL_METRIC",
        vertical_datum="TEST",
        block_cells=6,
        active_cells=int(arrays["active"].sum()),
        zone_ids=[1, 2],
        units=UNITS,
    )
    return dict(
        id="properties-" + suffix,
        revision=1,
        content_hash="a" * 64,
        kind="properties",
        summary=summary,
        paths={"grid.zip": str(path)},
    )


def params():
    return dict(
        scenarios=[
            dict(
                name="base",
                regions=[
                    dict(
                        region_id=1,
                        owc_z_m=5.0,
                        goc_z_m=15.0,
                        bo=1.2,
                        bg=0.005,
                        sg_in_oil_zone=0.0,
                        so_in_gas_zone=0.05,
                    ),
                    dict(region_id=2, owc_z_m=5.0, bo=1.2, sg_in_oil_zone=0.0),
                ],
            )
        ],
        region_field="FIPNUM",
        assumptions=["Synthetic explicit oil/gas control"],
        parameters_confirmed=True,
        polygon_ids=[],
        polygon_hole_ids=[],
    )


def test_regional_oil_gas_partial_cells_independent_integral(tmp_path):
    result = evaluate(model(tmp_path), params())
    a, b = result["tables"]["regions"]
    assert a["GRV"] == pytest.approx(4000)
    assert a["STOIIP"] == pytest.approx(200)
    assert a["GIIP"] == pytest.approx(22400)
    assert b["STOIIP"] == pytest.approx(150) and b["GIIP"] is None
    assert result["tables"]["scenarios"][0]["STOIIP"] == pytest.approx(350)
    assert all(v["status"] == "PASS" for v in result["independent_checks"])


def test_polygon_boundary_is_explicit_whole_cell_selection(tmp_path):
    path = tmp_path / "polygon.parquet"
    t = pa.table(
        dict(x=[0.0, 12.0, 12.0, 0.0, 0.0], y=[0.0, 0.0, 10.0, 10.0, 0.0], z=[0.0] * 5, polygon_id=["1"] * 5)
    )
    pq.write_table(t, path)
    polygon = dict(summary=dict(kind="polygons"), paths={"data.parquet": str(path)})
    p = params()
    p.update(polygon_ids=["1"], polygon_hole_ids=[], polygon_boundary="include")
    p["scenarios"][0]["regions"] = p["scenarios"][0]["regions"][:1]
    result = evaluate(model(tmp_path), p, polygon_geometry(polygon, p))
    row = result["tables"]["regions"][0]
    assert (
        row["selected_cells"] == 2
        and row["STOIIP"] == pytest.approx(100)
        and row["GIIP"] == pytest.approx(11200)
    )


def test_height_sw_table_and_leverett_explicit_parameters(tmp_path):
    obj = model(tmp_path)
    p = params()
    p["scenarios"][0]["regions"] = [
        dict(
            region_id=1,
            owc_z_m=5.0,
            bo=1.2,
            sg_in_oil_zone=0.0,
            sw_height=dict(method="table", table=[[0, 1], [10, 0]], extrapolation="clamp"),
        )
    ]
    assert evaluate(obj, p)["tables"]["regions"][0]["STOIIP"] == pytest.approx(320 / 1.2)
    case = p["scenarios"][0]["regions"][0]
    case["sw_height"] = dict(
        method="leverett_j",
        table=[[0.1, 1], [0.9, 0]],
        extrapolation="clamp",
        density_difference_kg_m3=200.0,
        surface_tension_mN_m=30.0,
        contact_angle_deg=0.0,
        gravity_m_s2=9.81,
    )
    j = 200 * 9.81 * 10 * np.sqrt(100 * 9.869233e-16 / 0.2) / 0.03
    sw = 0.9 - 0.8 * j
    expected = (2000 * 0.16 * (1 - sw) + 1000 * 0.16 * 0.1) / 1.2
    assert evaluate(obj, p)["tables"]["regions"][0]["STOIIP"] == pytest.approx(expected)


def test_qc_signed_twisted_property_and_cluster_witnesses(tmp_path):
    obj = model(tmp_path)
    out = tmp_path / "qc-good"
    out.mkdir()
    p = dict(region_field="FIPNUM", small_cluster_cells=1, max_examples=100, assumptions=[])
    result = model_qc(obj, p, out)
    assert result["status"] == "PASS" and result["validation_status"] == "PASS"
    assert result["clusters"]["total"] == 1

    def break_model(a):
        a["active"][:] = False
        a["active"][[0, 2]] = True
        a["phi"][0] = 1.2
        a["ntg"][0] = 0
        a["corners"][0] = a["corners"][0][[1, 0, 3, 2, 5, 4, 7, 6]]
        a["corners"][2, 7] = a["corners"][2, 0] + [0, 0, 5]

    broken = model(tmp_path, break_model, "broken")
    out = tmp_path / "qc-bad"
    out.mkdir()
    result = model_qc(broken, p, out)
    assert result["status"] == "ISSUES"
    assert result["counts"]["negative_signed_volume"] >= 1
    assert result["counts"]["twisted_cell"] >= 1
    assert result["counts"]["property_range:phi"] == 1
    assert result["counts"]["zero_pore_volume"] == 1
    assert result["clusters"]["total"] == 2
    assert any(v["i"] == 1 and v["j"] == 1 and v["k"] == 1 for v in result["examples"])


def test_revision_diff_region_pore_impact_and_reconcile_bo_evidence(tmp_path):
    a = model(tmp_path)

    def change(v):
        v["phi"][0] = 0.4

    b = model(tmp_path, change, "b")
    out = tmp_path / "diff"
    out.mkdir()
    result = model_diff(
        a, b, dict(region_field="FIPNUM", atol=0.0, rtol=0.0, max_examples=10, assumptions=[]), out
    )
    assert result["changed_cells"] == 1 and result["property_changed_cells"]["phi"] == 1
    assert result["tables"]["region_volume_impact"][0]["delta_PV"] == pytest.approx(160)
    assert result["validation_status"] == "PASS"
    path = tmp_path / "petrel.csv"
    path.write_text("region,metric,value,unit\n1,HCPV,240,m3\n1,STOIIP,160,sm3\n")
    p = params()
    p.update(
        reference_scenario="base",
        columns=dict(region_id="region", metric="metric", value="value", unit="unit"),
        metric_definitions=dict(HCPV="Oil HCPV", STOIIP="HCPV/Bo"),
        reference_region_definition="FIPNUM",
        relative_tolerance=1e-8,
    )
    result = reconcile(a, p, path)
    assert result["status"] == "DIFFERENCES"
    row = result["tables"]["reconciliation"][1]
    assert row["difference_m3"] == pytest.approx(40)
    assert row["probable_causes"][0]["cause"] == "Bo" and "1.5" in row["probable_causes"][0]["evidence"]
    json.dumps(result, allow_nan=False)


def test_original_las_along_survey_model_errors_and_gap_exclusions(tmp_path):
    obj = model(tmp_path)
    trajectory = tmp_path / "survey.parquet"
    pq.write_table(
        pa.table(dict(well_id=["A", "A"], md=[0.0, 30.0], x=[5.0, 5.0], y=[5.0, 5.0], z=[30.0, 0.0])),
        trajectory,
    )
    las = tmp_path / "las.parquet"
    pq.write_table(pa.table(dict(DEPT=[15.0, 25.0], PHI=[22.0, 18.0], NTG=[0.7, 0.9])), las)
    survey = dict(
        id="trajectory",
        revision=1,
        content_hash="b" * 64,
        summary=dict(kind="trajectory"),
        paths={"data.parquet": str(trajectory)},
    )
    log = dict(
        id="las",
        revision=1,
        content_hash="c" * 64,
        summary=dict(kind="las", well_id="A", units=dict(DEPT="m", PHI="%", NTG="fraction")),
        paths={"data.parquet": str(las)},
    )
    p = dict(
        logs=[
            dict(
                ref=dict(id="las", revision=1),
                md_curve="DEPT",
                property_curves=dict(phi="PHI", ntg="NTG"),
                property_units=dict(phi="percent", ntg="fraction"),
            )
        ],
        region_field="FIPNUM",
        max_survey_gap_m=31.0,
        boundary_policy="lowest_ijk",
        sample_every_n=1,
        assumptions=["Explicit unit and survey interpretation"],
    )
    out = tmp_path / "well-comparison"
    out.mkdir()
    result = wells_vs_model(obj, survey, [log], p, out)
    assert result["status"] == "COMPLETE" and result["validation_status"] == "PASS"
    rows = {r["property"]: r for r in result["tables"]["wells_zones"]}
    assert rows["phi"]["RMSE"] == pytest.approx(0.02)
    assert rows["ntg"]["RMSE"] == pytest.approx(0.1)
    assert rows["phi"]["bias_model_minus_LAS"] == pytest.approx(0, abs=1e-14)
    p["max_survey_gap_m"] = 10
    result = wells_vs_model(obj, survey, [log], p, out)
    assert result["status"] == "NO_COMPARABLE_SAMPLES" and result["validation_status"] == "NOT RUN"
    assert result["excluded"]["survey_gap_exceeds_user_limit"] == 4


def sensitivity_params():
    p = params()
    p.update(
        metric="STOIIP",
        max_cell_scenario_evaluations=100000,
        parameters=[
            dict(region_id=1, field="phi", mode="multiplier", low=0.5, high=1.5, distribution="uniform"),
            dict(region_id=2, field="ntg", mode="multiplier", low=0.5, high=1.0, distribution="uniform"),
        ],
    )
    return p


def test_tornado_known_linear_regional_impacts(tmp_path):
    p = sensitivity_params()
    out = tmp_path / "tornado"
    out.mkdir()
    result = tornado(model(tmp_path), p, out)
    a, b = result["tables"]["tornado"]
    assert a["parameter"] == "1.phi"
    assert a["metric_low"] == pytest.approx(250) and a["metric_high"] == pytest.approx(450)
    assert b["metric_low"] == pytest.approx(275) and b["metric_high"] == pytest.approx(350)
    assert result["validation_status"] == "PASS" and (out / "tornado.png").is_file()


def test_seeded_correlated_monte_carlo_every_result_and_quantiles(tmp_path):
    p = sensitivity_params()
    p.update(
        samples=32, seed=173, correlation=[[1.0, 0.75], [0.75, 1.0]], correlation_space="gaussian_copula"
    )
    sample = draws(p)
    expected = 200 * sample[:, 0] + 150 * sample[:, 1]
    out = tmp_path / "mc"
    out.mkdir()
    result = monte_carlo(model(tmp_path), p, out)
    values = {r["percentile"]: r["value"] for r in result["tables"]["percentiles"]}
    assert values["P90"] == pytest.approx(np.quantile(expected, 0.1))
    assert values["P50"] == pytest.approx(np.quantile(expected, 0.5))
    assert values["P10"] == pytest.approx(np.quantile(expected, 0.9))
    assert result["valid_samples"] == 32 and result["failed_samples"] == 0
    assert result["validation_status"] == "PASS" and (out / "s_curve.png").is_file()
    np.testing.assert_array_equal(sample, draws(p))
    p["samples"] = 4096
    sample = draws(p)
    # Gaussian-copula uniform marginals have a known nonlinear Pearson correlation.
    expected_correlation = 6 / np.pi * np.arcsin(0.75 / 2)
    assert np.corrcoef(sample, rowvar=False)[0, 1] == pytest.approx(expected_correlation, abs=0.04)
    p["correlation"] = [[1.0, 2.0], [2.0, 1.0]]
    with pytest.raises(DomainError, match="correlation"):
        draws(p)


def test_invalid_monte_carlo_draws_are_not_resampled_or_fabricated(tmp_path):
    p = sensitivity_params()
    p["parameters"] = p["parameters"][:1]
    p["parameters"][0].update(low=20.0, high=30.0)
    p.update(samples=4, seed=1, correlation=[[1.0]], correlation_space="gaussian_copula")
    out = tmp_path / "invalid-mc"
    out.mkdir()
    result = monte_carlo(model(tmp_path), p, out)
    assert result["status"] == "FAIL" and result["validation_status"] == "NOT RUN"
    assert result["valid_samples"] == 0 and result["failed_samples"] == 4
    assert result["tables"]["percentiles"] == []
    assert len((out / "mc_samples.csv").read_text().splitlines()) == 5


def test_invalid_revision_impacts_are_unavailable_and_twisted_volumes_fail_closed(tmp_path):
    original = model(tmp_path)

    def corrupt(a):
        a["corners"][0, 0, 0] = np.nan
        a["phi"][1] = 1.2

    invalid = model(tmp_path, changes=corrupt, suffix="invalid")
    out = tmp_path / "invalid-diff"
    out.mkdir()
    result = model_diff(
        original, invalid, dict(region_field="FIPNUM", atol=0, rtol=0, max_examples=10, assumptions=[]), out
    )
    impact = result["tables"]["region_volume_impact"][0]
    assert impact["after_GRV"] is None and impact["after_PV"] is None and impact["delta_HCPV"] is None

    def twist(a):
        a["corners"][0, [0, 1]] = a["corners"][0, [1, 0]]

    twisted = model(tmp_path, changes=twist, suffix="twisted")
    with pytest.raises(DomainError, match="degenerate/inverted/twisted"):
        evaluate(twisted, params())
