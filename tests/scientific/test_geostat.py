import numpy as np
import pytest
from test_numerics import fixture_arrays

from opensubsurface.adapters.geostat import conditioned
from opensubsurface.schemas import Geostat


def args():
    return Geostat.model_validate(
        dict(
            project_id="test",
            properties={"id": "x", "revision": 1},
            zone_id=1,
            field="phi",
            length_scale_m=100,
            conditioning=dict(
                positions=[[25, 25, -1015], [75, 25, -1015], [25, 75, -1015], [75, 75, -1015]],
                values=[0.15, 0.2, 0.25, 0.3],
                well_ids=["A", "B", "C", "D"],
            ),
        )
    ).model_dump(mode="json")


def test_exact_conditioning_transform_and_seed():
    p = args()
    arrays = fixture_arrays((2, 2, 2))
    grid = dict(shape=[2, 2, 2], extent=[0, 100, 0, 100, -1020, -1000])
    first, summary = conditioned(p, arrays, grid, "properties_simulate")
    second, _ = conditioned(p, arrays, grid, "properties_simulate")
    np.testing.assert_array_equal(first["phi"], second["phi"])
    np.testing.assert_allclose(first["phi"][:, :, 0].ravel(), [0.15, 0.25, 0.2, 0.3], atol=1e-6)
    assert summary["conditioning_max_abs_error"] < 1e-6
    assert summary["holdout"]["samples"] == 4
    assert np.all((first["phi"] > 0) & (first["phi"] < 1))


def test_zero_permeability_rejected_without_silent_log_fix():
    p = args()
    p["field"] = "permeability_md"
    p["conditioning"]["values"][0] = 0
    with pytest.raises(ValueError):
        Geostat.model_validate(p)


def test_anisotropic_ordinary_kriging_against_covariance_system():
    from scipy.spatial.distance import cdist
    from scipy.special import expit, logit

    p = args()
    p["anisotropy"] = [0.5, 0.2]
    p["length_scale_m"] = 40
    arrays = fixture_arrays((2, 2, 2))
    grid = dict(shape=[2, 2, 2], extent=[0, 100, 0, 100, -1020, -1000])
    modeled, _ = conditioned(p, arrays, grid, "properties_krige")
    observations = np.asarray(p["conditioning"]["positions"], float) / [1, 0.5, 0.2]
    target = np.array([[75, 75, -1005]]) / [1, 0.5, 0.2]
    covariance = np.exp(-cdist(observations, observations) / 40)
    matrix = np.block([[covariance, np.ones((4, 1))], [np.ones((1, 4)), np.zeros((1, 1))]])
    rhs = np.append(np.exp(-cdist(observations, target)[:, 0] / 40), 1.0)
    weights = np.linalg.solve(matrix, rhs)[:4]
    expected = expit(weights @ logit(p["conditioning"]["values"]))
    assert modeled["phi"][1, 1, 1] == pytest.approx(expected, abs=1e-10)
