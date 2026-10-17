import numpy as np
import pytest

from opensubsurface.calculations.validation import reference_volumes, statistics


def test_reference_layer_intersections_selected_zone_and_inactive_cells():
    arrays = dict(
        active=np.ones((2, 1, 2), bool),
        zones=np.array([[[1, 2]], [[1, 2]]]),
        phi=np.full((2, 1, 2), 0.2),
        ntg=np.full((2, 1, 2), 0.8),
        sw=np.full((2, 1, 2), 0.25),
    )
    grid = dict(shape=[2, 1, 2], extent=[0, 2, 0, 1, -20, 0])
    result = reference_volumes(arrays, grid, [1], -15, 1.2)
    assert result == pytest.approx(
        dict(GRV=20, GRV_oil_interval=10, NetRockVolume=8, PV=1.6, HCPV=1.2, STOIIP=1)
    )
    arrays["active"][1, 0, 0] = False
    assert reference_volumes(arrays, grid, [1], -15, 1.2)["STOIIP"] == pytest.approx(0.5)
    assert reference_volumes(arrays, grid, [1, 2], 1, 1.2)["STOIIP"] == 0


def test_independent_linear_quantiles_and_p_exceedance():
    result = statistics([0, 10, 20, 30])
    assert result["Q10"] == result["P90"] == pytest.approx(3)
    assert result["Q50"] == result["P50"] == 15
    assert result["Q90"] == result["P10"] == pytest.approx(27)
    assert result["mean"] == 15 and result["std"] == pytest.approx(125**0.5)
