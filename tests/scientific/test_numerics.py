import numpy as np
import pytest

from opensubsurface.domain.numerics import (
    from_opm,
    quantiles,
    seismic_attribute,
    time_to_z,
    to_opm,
    volumes,
    water_cut,
    z_to_time,
)
from opensubsurface.errors import DomainError


def fixture_arrays(shape=(10, 10, 2)):
    return dict(
        active=np.ones(shape, bool),
        zones=np.ones(shape, int),
        phi=np.full(shape, 0.2),
        ntg=np.full(shape, 0.8),
        sw=np.full(shape, 0.25),
        permeability_md=np.full(shape, 100.0),
        kz_ratio=np.full(shape, 0.1),
    )


def test_analytical_volume_all_metrics():
    grid = dict(shape=[10, 10, 2], extent=[0, 1000, 0, 1000, -1020, -1000])
    actual = volumes(fixture_arrays(), grid, [1], -1020, 1.2)["values"]
    expected = dict(GRV=20e6, GRV_oil_interval=20e6, NetRockVolume=16e6, PV=3.2e6, HCPV=2.4e6, STOIIP=2e6)
    for name, value in expected.items():
        assert actual[name] == pytest.approx(value, rel=1e-8)


def test_fractional_contact_and_missing_active():
    arrays = fixture_arrays((1, 1, 1))
    grid = dict(shape=[1, 1, 1], extent=[0, 1000, 0, 1000, -1020, -1000])
    result = volumes(arrays, grid, [1], -1010, 1.2)["values"]
    assert result["GRV"] == 20e6
    assert result["STOIIP"] == pytest.approx(1e6, rel=1e-8)
    arrays["phi"][0, 0, 0] = np.nan
    with pytest.raises(DomainError, match="Пропуски"):
        volumes(arrays, grid, [1], -1010, 1.2)


def test_inactive_nan_does_not_poison():
    arrays = fixture_arrays((2, 1, 1))
    arrays["active"][0] = False
    arrays["phi"][0] = np.nan
    grid = dict(shape=[2, 1, 1], extent=[0, 1000, 0, 1000, -1020, -1000])
    assert volumes(arrays, grid, [1], -1020, 1.2)["values"]["STOIIP"] == pytest.approx(1e6)


def test_asymmetric_mapping_has_independent_expected_order():
    x = np.arange(24).reshape(3, 4, 2)
    # I fastest, then J, topmost K first; independent hardcoded expected fixture.
    expected = [1, 9, 17, 3, 11, 19, 5, 13, 21, 7, 15, 23, 0, 8, 16, 2, 10, 18, 4, 12, 20, 6, 14, 22]
    assert to_opm(x).tolist() == expected
    np.testing.assert_array_equal(from_opm(expected, (3, 4, 2)), x)
    active = np.ones((3, 4, 2), bool)
    active[1, 2, 0] = False
    active[0, 0, 1] = False
    restored = from_opm(to_opm(x)[to_opm(active)], (3, 4, 2), active)
    np.testing.assert_array_equal(restored[active], x[active])
    assert np.isnan(restored[~active]).all()


def test_rms_constant_boundaries_and_impulse():
    cube = np.full((2, 3, 32), 3.5)
    np.testing.assert_allclose(seismic_attribute(cube, "rms", 5), 3.5, atol=1e-12)
    impulse = np.zeros((1, 1, 11))
    impulse[..., 5] = 1
    expected = np.zeros((1, 1, 11))
    expected[..., 3:8] = np.sqrt(0.2)
    np.testing.assert_allclose(seismic_attribute(impulse, "rms", 5), expected, atol=1e-12)


def test_envelope_integer_cycles_and_mask():
    sine = 2.75 * np.sin(2 * np.pi * 8 * np.arange(128) / 128)
    result = seismic_attribute(sine[None, None, :], "envelope")
    np.testing.assert_allclose(result, 2.75, atol=1e-10)
    cube = np.tile(sine, (2, 1, 1))
    cube[0, 0, 20] = np.nan
    result = seismic_attribute(cube, "envelope")
    assert np.isnan(result[0]).all()
    assert np.isfinite(result[1]).all()


def test_time_depth_expected_and_roundtrip():
    assert time_to_z(0.5, 2000, 100) == -400
    values = np.array([0.1, 0.2, 0.5])
    np.testing.assert_allclose(z_to_time(time_to_z(values, 2300, 30), 2300, 30), values, atol=1e-15)


def test_quantile_exceedance_and_undefined_water_cut():
    stats = quantiles(np.arange(11))
    assert stats["Q10"] == stats["P90"] == 1
    assert stats["Q90"] == stats["P10"] == 9
    cut = water_cut([0, 3, 1], [0, 1, 3])
    assert np.isnan(cut[0])
    assert cut[1:].tolist() == [0.25, 0.75]


def test_faulted_opm_bridge_rejects_without_voxelization_claim(tmp_path):
    from opensubsurface.adapters.opm import generate_case

    with pytest.raises(DomainError, match="Наклонный"):
        generate_case({}, {}, {}, tmp_path, {"fault": True})


def test_tabulated_time_depth_and_no_extrapolation():
    from opensubsurface.domain.numerics import table_time_to_z, table_z_to_time

    table = [[0, 0], [0.2, 180], [0.5, 600]]
    times = np.array([0.1, 0.3, 0.4])
    z = table_time_to_z(times, table, 100)
    np.testing.assert_allclose(z, [10, -220, -360], atol=1e-12)
    np.testing.assert_allclose(table_z_to_time(z, table, 100), times, atol=1e-15)
    with pytest.raises(DomainError, match="extrapolation"):
        table_time_to_z(0.6, table, 100)
