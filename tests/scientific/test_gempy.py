import numpy as np
import pandas as pd

from opensubsurface.adapters.structure import gempy_build


def test_horizontal_gempy_cpu_independent_boundary():
    p = dict(
        grid=dict(shape=[3, 4, 8], extent=[0, 1000, 0, 1000, -1040, -1000]),
        horizontal_assumption=True,
        execution=dict(precision="float64"),
    )
    points = pd.DataFrame(
        dict(horizon=["top"] * 4, x=[0, 1000, 0, 1000], y=[0, 0, 1000, 1000], z=[-1020] * 4)
    )
    zones, summary = gempy_build(p, points, None, "cpu")
    assert zones.shape == (3, 4, 8)
    np.testing.assert_array_equal(zones[:, :, 0], np.full((3, 4), 2))
    np.testing.assert_array_equal(zones[:, :, -1], np.full((3, 4), 1))
    assert (np.diff(zones, axis=2) != 0).sum() == 12
    assert summary["coordinate_transform"]["position"] == [-500.0, -500.0, 1020.0]


def test_dipping_layers_resolution_convergence():
    slope = 0.187
    top = -73.0
    points = pd.DataFrame(
        [dict(horizon="H", x=x, y=y, z=top + slope * x) for x in [0, 200] for y in [0, 100]]
    )
    normal = np.array([-slope, 0, 1])
    normal /= np.linalg.norm(normal)
    orient = pd.DataFrame(
        [dict(horizon="H", x=100, y=50, z=top + slope * 100, nx=normal[0], ny=normal[1], nz=normal[2])]
    )
    errors = []
    for n in [10, 20, 40]:
        p = dict(
            grid=dict(shape=[n, 2, n], extent=[0, 200, 0, 100, -100, 0]),
            horizontal_assumption=False,
            execution=dict(precision="float64"),
        )
        zones, _ = gempy_build(p, points, orient, "cpu")
        actual = []
        for i in range(n):
            changes = np.where(np.diff(zones[i, 0]) != 0)[0]
            assert len(changes) == 1
            actual.append(-100 + (changes[0] + 1) * 100 / n)
        expected = top + slope * ((np.arange(n) + 0.5) * 200 / n)
        error = float(np.mean(np.abs(np.asarray(actual) - expected)))
        assert np.max(np.abs(np.asarray(actual) - expected)) <= 100 / n
        errors.append(error)
    assert errors[2] < errors[1] < errors[0]


def test_single_planar_fault_geometry_and_direction():
    p = dict(
        grid=dict(shape=[20, 4, 20], extent=[0, 200, 0, 100, -100, 0]),
        horizontal_assumption=False,
        execution=dict(precision="float64"),
    )
    surfaces = pd.DataFrame(
        [
            dict(horizon="H", x=x, y=y, z=z)
            for x, z in [(20, -40), (60, -40), (140, -60), (180, -60)]
            for y in [0, 100]
        ]
    )
    orient = pd.DataFrame(
        [dict(horizon="H", x=x, y=50, z=z, nx=0, ny=0, nz=1) for x, z in [(50, -40), (150, -60)]]
    )
    fault = dict(
        name="F", points=[[100, 0, -100], [100, 100, -100], [100, 100, 0], [100, 0, 0]], normal=[1, 0, 0]
    )
    zones, summary = gempy_build(p, surfaces, orient, "cpu", fault)
    assert set(np.unique(zones)) == {2, 3}
    for i, expected in [(8, -40), (9, -40), (10, -60), (11, -60)]:
        changes = np.where(np.diff(zones[i, 2]) != 0)[0]
        assert len(changes) == 1
        assert abs((-100 + (changes[0] + 1) * 5) - expected) <= 5
    assert summary["fault_geometry"] == fault
