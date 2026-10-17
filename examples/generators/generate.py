"""Synthetic datasets; all generated data Apache-2.0, no commercial field data."""

import csv
import json
from pathlib import Path

import numpy as np


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def generate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_csv(
        output / "collars.csv",
        [
            dict(well_id=w, x=x, y=y, reference_elevation=0)
            for w, x, y in [("W-01", 250, 250), ("W-02", 750, 750)]
        ],
    )
    write_csv(
        output / "trajectory.csv",
        [
            dict(well_id=w, md=md, x=x, y=y, z=-md)
            for w, x, y in [("W-01", 250, 250), ("W-02", 750, 750)]
            for md in [0, 1000, 1020, 1050]
        ],
    )
    write_csv(
        output / "markers.csv",
        [
            dict(well_id=w, horizon=h, md=md)
            for w in ["W-01", "W-02"]
            for h, md in [("Top", 1000), ("Base", 1020)]
        ],
    )
    for name, dip in [("layer_cake", 0), ("dipping_layers", 0.02)]:
        write_csv(
            output / (name + ".csv"),
            [
                dict(horizon=h, x=x, y=y, z=z + dip * x)
                for h, z in [("Top", -1000), ("Base", -1020)]
                for x, y in [(0, 0), (1000, 0), (0, 1000), (1000, 1000)]
            ],
        )
    write_csv(
        output / "orientations.csv",
        [dict(horizon=h, x=500, y=500, z=z, nx=0, ny=0, nz=1) for h, z in [("Top", -1000), ("Base", -1020)]],
    )
    # This fixture is input geometry only; does not claim a validated fault adapter.
    write_csv(
        output / "single_fault.csv",
        [
            dict(horizon="Fault", x=500, y=y, z=z)
            for y, z in [(0, -1050), (1000, -1050), (0, -980), (1000, -980)]
        ],
    )
    write_csv(
        output / "faulted_layers.csv",
        [
            dict(horizon="H", x=x, y=y, z=z)
            for x, z in [(20, -40), (60, -40), (140, -60), (180, -60)]
            for y in [0, 100]
        ],
    )
    write_csv(
        output / "faulted_orientations.csv",
        [dict(horizon="H", x=x, y=50, z=z, nx=0, ny=0, nz=1) for x, z in [(50, -40), (150, -60)]],
    )
    (output / "planar_fault.json").write_text(
        json.dumps(
            dict(
                name="F",
                points=[[100, 0, -100], [100, 100, -100], [100, 100, 0], [100, 0, 0]],
                normal=[1, 0, 0],
            ),
            indent=2,
        )
    )
    for well, offset in [("W-01", 0), ("W-02", 0.02)]:
        lines = [
            "~Version Information",
            " VERS. 2.0 : VERSION",
            " WRAP. NO : ONE LINE PER DEPTH",
            "~Well Information",
            " STRT.M 990 : START",
            " STOP.M 1030 : STOP",
            " STEP.M 1 : STEP",
            " NULL. -999.25 : NULL",
            f" WELL. {well} : WELL",
            "~Curve Information",
            " DEPT.M : Measured depth",
            " PHI.V/V : Porosity",
            " GR.API : Gamma ray",
            "~A",
        ]
        for md in range(990, 1031):
            phi = -999.25 if md == 1007 else 0.2 + offset + 0.015 * np.sin(md * 0.4)
            lines.append(f"{md} {phi:.8f} {60 + 20 * np.cos(md * 0.2):.5f}")
        (output / (well + ".las")).write_text("\n".join(lines) + "\n")
    write_csv(
        output / "invalid_trajectory.csv",
        [dict(well_id="W-01", md=10, x=0, y=0, z=-10), dict(well_id="W-01", md=5, x=0, y=0, z=-5)],
    )
    (output / "zones.json").write_text(
        json.dumps({"1": dict(phi=0.2, ntg=0.8, sw=0.25, permeability_md=100)}, indent=2)
    )
    (output / "provenance.json").write_text(
        json.dumps(
            dict(
                license="Apache-2.0",
                seed=42,
                crs="LOCAL_METRIC",
                vertical_datum="SYNTHETIC_MSL",
                coordinates_unit="m",
                notes="Synthetic geological fixtures, not measured field data",
            ),
            indent=2,
        )
    )
    return str(output)


if __name__ == "__main__":
    import sys

    print(generate(sys.argv[1] if len(sys.argv) > 1 else "examples/templates"))
