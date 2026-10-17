"""Independent corner-point integral: clip each declared tetrahedron by convex hull.

Shares only immutable storage and the documented six-tetrahedron cell definition.
No production clipping or volume functions are called.
"""

import itertools
import math

import numpy as np
from scipy.spatial import ConvexHull


def integral(corners, contact=None):
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


def reference(obj, cases):
    from opensubsurface.adapters.cornerpoint import blocks, open_grid

    totals = [[[] for _ in range(5)] for _ in cases]
    counts = [0] * len(cases)
    with open_grid(obj) as group:
        for _, data in blocks(group):
            for i, case in enumerate(cases):
                mask = (data["active"] == 1) & np.isin(data["zones"], case["zone_ids"])
                counts[i] += int(mask.sum())
                corners = data["corners"][mask]
                whole, oil = integral(corners), integral(corners, case["contact_z_m"])
                override = case.get("overrides", {})
                phi, ntg, sw = [override.get(k, data[k][mask]) for k in ("phi", "ntg", "sw")]
                net, pore = oil * ntg, oil * ntg * phi
                for result, values in zip(totals[i], (whole, oil, net, pore, pore * (1 - sw))):
                    result.append(float(np.sum(values, dtype=np.float64)))
    results = []
    for i, case in enumerate(cases):
        if not counts[i]:
            raise ValueError("No active selected cells")
        values = dict(
            zip(
                ("GRV", "GRV_oil_interval", "NetRockVolume", "PV", "HCPV"),
                [math.fsum(part) for part in totals[i]],
            )
        )
        values["STOIIP"] = values["HCPV"] / case["bo"]
        results.append(values)
    return results
