"""Full unmodified DATA acceptance; independent XTGeo geometry and original-property controls."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np
import xtgeo
import zarr

from opensubsurface.adapters.eclipse_import import import_deck
from opensubsurface.adapters.grdecl_properties import fill
from opensubsurface.adapters.local_sources import LocalSources, path_revision
from opensubsurface.service import Service

ROOT = Path("examples/reference/norne/full").resolve()


def original(relative, keyword, cells):
    a = np.empty(cells)
    fd = os.open(ROOT / "norne" / relative, os.O_RDONLY)
    try:
        fill(fd, a, keyword, cells, 16384, hashlib.sha256())
    finally:
        os.close(fd)
    return a


def main():
    started = time.monotonic()
    path = ROOT / "norne/NORNE_ATW2013.DATA"
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest()
        == "f346c910f68a80b41ee54606bd434dc9e2993fffa7a2469235f396c2c0a9e080"
    )
    with tempfile.TemporaryDirectory(prefix="norne-data-") as temporary:
        base = Path(temporary)
        service = Service(base / "home")
        source = LocalSources(service.store).register("Full public Norne", ROOT)
        out = base / "output"
        out.mkdir()
        p = dict(
            path="norne/NORNE_ATW2013.DATA",
            file_revision=path_revision(path),
            length_unit="m",
            z_direction="down",
            defaults={},
            region_field="FIPNUM",
            crs="LOCAL_METRIC",
            vertical_datum="SOURCE DEPTH REFERENCE FOR IMPORT TEST ONLY",
            assumptions=[
                "Import-only upstream Norne acceptance; CRS/datum not inferred, no reserves estimate",
                "SWATINIT is not silently substituted for equilibrium SWAT",
            ],
            block_cells=16384,
        )
        _, summary, files = import_deck(dict(source=source), p, out)
        cells = 46 * 112 * 22
        native = xtgeo.grid_from_file(ROOT / "norne/INCLUDE/GRID/IRAP_1005.GRDECL", fformat="grdecl")
        native_zcorn_ulp = float(np.max(np.abs(np.spacing(native._zcornsv))))
        expected_corners = np.stack(
            [v.values.ravel(order="F") for v in native.get_xyz_corners()], axis=1
        ).reshape(-1, 8, 3)
        expected_corners[:, :, 2] *= -1
        # Native ZCORN uses float32. Bound interpolation error from dtype ULP
        # and pillar slopes before comparing; retain full float64 source values.
        pillars = native._coordsv.reshape(-1, 6)
        dz = pillars[:, 5] - pillars[:, 2]
        slope = np.max(
            np.divide(
                np.abs(pillars[:, 3:5] - pillars[:, :2]),
                np.abs(dz[:, None]),
                out=np.zeros((len(pillars), 2)),
                where=dz[:, None] != 0,
            )
        )
        native_precision_bound = float(4 * native_zcorn_ulp * (1 + slope))
        checks = {}
        with zarr.ZipStore(str(files["grid.zip"]), mode="r") as store:
            g = zarr.open_group(store=store)
            np.testing.assert_allclose(g["corners"][:], expected_corners, rtol=0, atol=native_precision_bound)
            checks["all_corners_against_xtgeo"] = "PASS"
            checks["xtgeo_float32_zcorn_derived_bound_m"] = native_precision_bound
            checks["xtgeo_max_coordinate_difference_m"] = float(
                np.max(np.abs(g["corners"][:] - expected_corners))
            )
            for name, keyword, filename in [
                ("active", "ACTNUM", "GRID/ACTNUM_0704.prop"),
                ("phi", "PORO", "PETRO/PORO_0704.prop"),
                ("ntg", "NTG", "PETRO/NTG_0704.prop"),
                ("permeability_md", "PERMX", "PETRO/PERM_0704.prop"),
                ("FIPNUM", "FIPNUM", "PETRO/FIPNUM_0704.prop"),
                ("EQLNUM", "EQLNUM", "PETRO/EQLNUM_0704.prop"),
            ]:
                expected = original("INCLUDE/" + filename, keyword, cells)
                np.testing.assert_array_equal(g[name][:], expected)
                checks[keyword + "_every_original_value"] = "PASS"
            expected_ratio = np.repeat(
                [
                    0.2,
                    0.04,
                    0.25,
                    0,
                    0.13,
                    0.13,
                    0.13,
                    0.13,
                    0.09,
                    0.07,
                    0.19,
                    0.13,
                    0.64,
                    0.64,
                    0.64,
                    0.64,
                    0.64,
                    0.016,
                    0.004,
                    0.004,
                    1,
                    1,
                ],
                46 * 112,
            )
            kx = g["permeability_md"][:]
            np.testing.assert_allclose(g["PERMZ"][:], kx * expected_ratio)
            checks["COPY_MULTIPLY_PERMZ_by_layer"] = "PASS"
            assert np.all(g["SATNUM"][:] == 1)
            assert np.isnan(g["sw"][:]).all()
            checks["missing_SWAT_not_fabricated"] = "PASS"
        report = json.loads(files["import_report.json"].read_text())
        assert "SWAT" in report["missing_properties"]
        assert any(v["keyword"] == "MINPV" for v in report["unsupported_keywords"])
        record = dict(
            status="PASS",
            source="Unmodified full NORNE_ATW2013.DATA + complete INCLUDE closure",
            root_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            files_read=len(report["source_files"]),
            cells=cells,
            active_cells=summary["active_cells"],
            checks=checks,
            seconds=time.monotonic() - started,
            scope="Static import only; no OPM run or equilibrium SWAT; source units/datum require user confirmation",
            unsupported_keywords=report["unsupported_keywords"],
        )
        Path("docs/norne-data-check.json").write_text(json.dumps(record, indent=2) + "\n")
        service.close()
        print(json.dumps({k: v for k, v in record.items() if k != "unsupported_keywords"}, indent=2))


if __name__ == "__main__":
    main()
