"""Independent corner-point integral: exact barycentric half-space fractions.

Shares only immutable storage and the documented six-tetrahedron cell definition.
No production clipping or volume functions are called.
"""

import math

import numpy as np


def tetra_fraction(depth):
    """Fraction of a simplex in z>0, using barycentric divided differences.

    For two positive depths p,q and negative depths -r,-s the divided
    difference is expanded algebraically, avoiding p-q (including p=q).
    This uses no intersection coordinates or production tetrahedra clipping.
    Scaling depths prevents overflow and leaves repeated plane vertices exact.
    """
    depth = np.sort(np.asarray(depth, dtype=np.float64), axis=1)
    count = (depth > 0).sum(axis=1)
    fraction = np.zeros(len(depth))
    fraction[count == 4] = 1
    for n in (1, 2, 3):
        mask = count == n
        d = depth[mask]
        if not len(d):
            continue
        d = d / np.max(np.abs(d), axis=1)[:, None]
        if n == 1:
            p = d[:, 3, None]
            fraction[mask] = np.prod(p / (p - d[:, :3]), axis=1)
        elif n == 3:
            r = -d[:, :1]
            fraction[mask] = 1 - np.prod(r / (r + d[:, 1:]), axis=1)
        else:
            r, s, p, q = -d[:, 0], -d[:, 1], d[:, 2], d[:, 3]
            numerator = p * p * q * q + (r + s) * p * q * (p + q) + r * s * (p * p + p * q + q * q)
            fraction[mask] = numerator / ((p + r) * (p + s) * (q + r) * (q + s))
    return fraction


def integral(corners, contact=None):
    corners = np.asarray(corners, dtype=np.float64)
    answer = np.zeros(len(corners))
    for indices in ((0, 1, 3, 7), (0, 1, 5, 7), (0, 2, 3, 7), (0, 2, 6, 7), (0, 4, 5, 7), (0, 4, 6, 7)):
        vertices = corners[:, indices]
        whole = np.abs(np.linalg.det(vertices[:, 1:] - vertices[:, :1])) / 6
        answer += whole if contact is None else whole * tetra_fraction(vertices[:, :, 2] - contact)
    return answer


def _reference_block(start, data, order, cases):
    parts, counts = [], []
    for case in cases:
        mask = (data["active"] == 1) & np.isin(data["zones"], case["zone_ids"])
        counts.append(int(mask.sum()))
        corners = data["corners"][mask]
        whole, oil = integral(corners), integral(corners, case["contact_z_m"])
        override = case.get("overrides", {})
        phi, ntg, sw = [override.get(k, data[k][mask]) for k in ("phi", "ntg", "sw")]
        net, pore = oil * ntg, oil * ntg * phi
        parts.append([math.fsum(map(float, v)) for v in (whole, oil, net, pore, pore * (1 - sw))])
    return parts, counts


def reference(obj, cases):
    from opensubsurface.execution.blocks import mapped

    totals = [[[] for _ in range(5)] for _ in cases]
    counts = [0] * len(cases)
    for parts, nums in mapped(obj, _reference_block, cases):
        for i in range(len(cases)):
            counts[i] += nums[i]
            for target, value in zip(totals[i], parts[i]):
                target.append(value)
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
