"""Bounded DATA generator with rational analytic volume expectations.

Ten layers ensure the horizontal contact cuts exactly 10% of ordinary cells.
The shifted pillar band is a fault-like discontinuity; a zero-height pillar
creates ten valid pinched cells, and three deliberately twisted cells exercise
strict rejection and explicitly reported exclusions. No random subsampling.
"""

import argparse
import json
import math
from fractions import Fraction as F
from pathlib import Path

import numpy as np

SHAPES = {
    10_000_000: (1000, 1000, 10),
    50_000_000: (2500, 2000, 10),
    100_000_000: (4000, 2500, 10),
    200_000_000: (5000, 4000, 10),
}
TETS = ((0, 1, 3, 7), (0, 1, 5, 7), (0, 2, 3, 7), (0, 2, 6, 7), (0, 4, 5, 7), (0, 4, 6, 7))


def exact_cell(vertices, contact=None):
    """Analytic rational determinant + simplex polynomial, no production calls."""
    total = F(0)
    for tet in TETS:
        v = [[F(x) for x in vertices[i]] for i in tet]
        a, b, c = [[v[i][j] - v[0][j] for j in range(3)] for i in (1, 2, 3)]
        det = (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        )
        fraction = F(1)
        if contact is not None:
            depth = sorted(p[2] - F(contact) for p in v)
            n = sum(x > 0 for x in depth)
            if n == 0:
                fraction = F(0)
            elif n == 1:
                fraction = math.prod(depth[3] / (depth[3] - x) for x in depth[:3])
            elif n == 3:
                fraction = 1 - math.prod(-depth[0] / (x - depth[0]) for x in depth[1:])
            elif n == 2:
                r, s, p, q = -depth[0], -depth[1], depth[2], depth[3]
                fraction = (p * p * q * q + (r + s) * p * q * (p + q) + r * s * (p * p + p * q + q * q)) / (
                    (p + r) * (p + s) * (q + r) * (q + s)
                )
        total += abs(det) * fraction / 6
    return total


def generate(directory, shape):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    nx, ny, nz = shape
    if nz != 10 or nx < 10 or ny < 1:
        raise ValueError("Use ten layers and NX>=10 for the analytic five-region fixture")
    cells = nx * ny * nz
    contact = F(-45, 2)
    corrections = [F(0), F(0)]
    for k in range(nz):
        v = [[10 * (c % 2), 20 * ((c // 2) % 2), -5 * (k + c // 4)] for c in range(8)]
        v[0][2] = v[4][2] = 0
        corrections[0] += exact_cell(v) - 1000
        ordinary_oil = 200 * max(F(0), min(F(5), F(-5 * k) - contact))
        corrections[1] += exact_cell(v, contact) - ordinary_oil
    path = directory / "MODEL.DATA"
    z_edits = {}
    for k in range(nz):
        for dk in (0, 1):
            z_edits[((2 * k + dk) * 2 * ny) * 2 * nx] = 0
    twisted = [2, 3, 4]
    for i in twisted:
        z_edits[((1) * 2 * ny + 1) * 2 * nx + 2 * i + 1] = -5
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(f"RUNSPEC\nDIMENS\n{nx} {ny} {nz} /\nMETRIC\nGRID\nCOORD\n")
        x = np.arange(nx + 1) * 10
        x[x >= (nx // 2) * 10] += 3
        for j in range(ny + 1):
            row = np.column_stack(
                (
                    x,
                    np.full(nx + 1, j * 20),
                    np.zeros(nx + 1),
                    x,
                    np.full(nx + 1, j * 20),
                    np.full(nx + 1, nz * 5),
                )
            )
            if j == 0:
                row[0, 5] = 0
            np.savetxt(stream, row, fmt="%d")
        stream.write("/\nZCORN\n")
        width = 4 * nx * ny
        for plane in range(2 * nz):
            start, end = plane * width, (plane + 1) * width
            value = ((plane + 1) // 2) * 5
            position = start
            for index in sorted(i for i in z_edits if start <= i < end):
                if index > position:
                    stream.write(f"{index - position}*{value}\n")
                stream.write(f"{z_edits[index]}\n")
                position = index + 1
            if position < end:
                stream.write(f"{end - position}*{value}\n")
        stream.write("/\n")
        for key, value in dict(ACTNUM=1, PORO=0.2, NTG=0.8, SWAT=0.25, PERMX=100, PERMZ=10).items():
            stream.write(f"{key}\n{cells}*{value} /\n")
        for key in ("EQLNUM", "FIPNUM"):
            stream.write(key + "\n")
            for _ in range(ny * nz):
                stream.write(
                    " ".join(
                        f"{math.ceil(r * nx / 5) - math.ceil((r - 1) * nx / 5)}*{r}" for r in range(1, 6)
                    )
                    + "\n"
                )
            stream.write("/\n")
        stream.write("END\n")
    expected = []
    for region in range(1, 6):
        first, last = math.ceil((region - 1) * nx / 5), math.ceil(region * nx / 5)
        span = (last - first) * 10 + (3 if first <= nx // 2 - 1 < last else 0)
        grv, oil = F(span * ny * 20 * nz * 5), F(span * ny * 20) * (-contact)
        if region == 1:
            grv += corrections[0]
            oil += corrections[1]
        excluded = sum(first <= i < last for i in twisted)
        grv -= excluded * 1000
        oil -= excluded * 1000
        expected.append(
            dict(
                region_id=region,
                GRV=float(grv),
                GRV_oil_interval=float(oil),
                STOIIP=float(oil / 10),
                GRV_exact=str(grv),
                STOIIP_exact=str(oil / 10),
            )
        )
    manifest = dict(
        shape=list(shape),
        cells=cells,
        contact_z_m=float(contact),
        bo=1.2,
        geometry_policy="exclude_flagged",
        parameters_confirmed=True,
        explicit_excluded_cell_ids=twisted,
        pinched_cell_ids=[k * nx * ny for k in range(nz)],
        ordinary_intersected_cell_fraction=0.1,
        expected_regions=expected,
        scope="Synthetic fault-like shifted pillars, one collapsed pillar, three deliberately twisted active cells",
    )
    (directory / "analytic.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path, manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--cells", type=int, choices=SHAPES, default=10_000_000)
    args = parser.parse_args()
    print(generate(args.directory, SHAPES[args.cells])[0])
