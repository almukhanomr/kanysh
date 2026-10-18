"""Slow pre-scaling Qhull oracle; deliberately test-only."""

import itertools

import numpy as np
from scipy.spatial import ConvexHull


def hull_integral(corners, contact=None):
    answer = np.zeros(len(corners))
    for indices in ((0, 1, 3, 7), (0, 1, 5, 7), (0, 2, 3, 7), (0, 2, 6, 7), (0, 4, 5, 7), (0, 4, 6, 7)):
        vertices = corners[:, indices]
        edges = vertices[:, 1:] - vertices[:, :1]
        whole = np.abs(np.linalg.det(edges)) / 6
        if contact is None:
            answer += whole
            continue
        above = vertices[:, :, 2] > contact
        full = above.all(axis=1)
        answer[full] += whole[full]
        partial = np.flatnonzero(above.any(axis=1) & ~full & (whole > 1e-15))
        for index in partial:
            v = vertices[index]
            points = [point for point in v if point[2] >= contact]
            for a, b in itertools.combinations(v, 2):
                if (a[2] < contact < b[2]) or (b[2] < contact < a[2]):
                    points.append(a + (b - a) * ((contact - a[2]) / (b[2] - a[2])))
            # Translation reduces Qhull precision loss for UTM coordinates.
            points = np.unique(np.asarray(points), axis=0)
            if len(points) >= 4:
                answer[index] += ConvexHull(points - points[0]).volume
    return answer
