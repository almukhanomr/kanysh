import numpy as np
import pytest
from hull_reference import hull_integral

from opensubsurface.calculations.cornerpoint_reference import integral, tetra_fraction


@pytest.mark.parametrize("contact", [-2.0, -0.25, 0.0, 0.25, 2.0])
def test_barycentric_integral_matches_old_qhull(contact):
    rng = np.random.default_rng(123)
    corners = rng.normal(size=(80, 8, 3))
    np.testing.assert_allclose(
        integral(corners, contact), hull_integral(corners, contact), rtol=1e-10, atol=1e-12
    )


def test_repeated_depths_plane_vertices_and_complement():
    depths = np.array(
        [[1, -1, -1, -1], [1, 1, -1, -1], [1, 1, 1, -1], [0, 0, 0, 0], [0, 1, 1, -1], [0, 0, 1, -1]], float
    )
    np.testing.assert_allclose(tetra_fraction(depths), [0.125, 0.5, 0.875, 0, 0.75, 0.5], rtol=1e-15)
    random = np.random.default_rng(1).normal(size=(10000, 4))
    np.testing.assert_allclose(tetra_fraction(random) + tetra_fraction(-random), 1, rtol=0, atol=1e-15)


def test_reference_never_calls_production_geometry(monkeypatch):
    from opensubsurface.adapters import cornerpoint

    def forbidden(*args, **kwargs):
        raise AssertionError("Independent integral called production code")

    monkeypatch.setattr(cornerpoint, "cell_volumes", forbidden)
    monkeypatch.setattr(cornerpoint, "clipped_tetra", forbidden)
    assert np.isfinite(integral(np.random.default_rng(8).normal(size=(32, 8, 3)), 0.5)).all()


def test_large_map_coordinates_against_translation_stable_hull():
    corners = np.random.default_rng(123).normal(size=(80, 8, 3))
    corners[:, :, :2] += [500000, 7500000]
    # Form intersection points locally: the old oracle rounds metre-sized
    # intersections at map coordinates before its Qhull translation.
    local = corners.copy()
    local[:, :, :2] -= corners[:, :1, :2]
    np.testing.assert_allclose(integral(corners, 0.25), hull_integral(local, 0.25), rtol=1e-10, atol=1e-12)
