"""Explicit interchange adapters using XTGeo, with canonical metric/Z-up datasets."""

import shlex

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import xtgeo

from opensubsurface.adapters.copilot_report import write_report
from opensubsurface.adapters.source_files import copy_file
from opensubsurface.errors import require


def cps_surface(path, p):
    header, values, data = {}, [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("->"):
            data = True
            continue
        if not line.strip():
            continue
        if data:
            values.extend(float(v.replace("D", "E")) for v in line.split())
            require(len(values) <= 2_000_000, "UNSUPPORTED_PROFILE", "CPS-3 node limit 2M")
        else:
            key, *rest = shlex.split(line)
            require(
                key in {"FSASCI", "FSATTR", "FSLIMI", "FSNROW", "FSXINC"},
                "UNSUPPORTED_FORMAT",
                "Unknown CPS-3 header: " + key,
            )
            header[key] = rest
    require(
        {"FSASCI", "FSLIMI", "FSNROW", "FSXINC"} <= header.keys(), "INVALID_FORMAT", "Incomplete CPS-3 header"
    )
    ny, nx = map(int, header["FSNROW"][:2])
    require(
        nx > 1 and ny > 1 and nx * ny <= 2_000_000 and len(values) == nx * ny,
        "INVALID_FORMAT",
        "CPS-3 dimensions/value count",
    )
    xmin, xmax, ymin, ymax = map(float, header["FSLIMI"][:4])
    dx, dy = map(float, header["FSXINC"][:2])
    require(
        np.isclose(dx * (nx - 1), xmax - xmin) and np.isclose(dy * (ny - 1), ymax - ymin),
        "UNSUPPORTED_PROFILE",
        "CPS-3 node bounds/increments inconsistent",
    )
    require(
        p["cps_order"] is not None and p["cps_y_first"] is not None,
        "NEEDS_INPUT",
        "Confirm CPS-3 value order and first Y row from export settings",
    )
    null = float(header["FSASCI"][4])
    a = np.asarray(values).reshape((ny, nx), order="C" if p["cps_order"] == "row_major" else "F").T
    if p["cps_y_first"] == "max":
        a = a[:, ::-1]
    a = np.ma.masked_where(np.isclose(a, null, rtol=1e-7, atol=0) | ~np.isfinite(a), a)
    return xtgeo.RegularSurface(nx, ny, xinc=dx, yinc=dy, xori=xmin, yori=ymin, values=a)


def ascii_table(path, p):
    if p["delimiter"] is not None:
        data = pd.read_csv(path, sep=p["delimiter"], skiprows=p["skiprows"])
        require(bool(p["columns"]), "NEEDS_INPUT", "Explicit column mapping required")
        require(set(p["columns"].values()) <= set(data.columns), "INVALID_FORMAT", "Mapped column missing")
        return data.rename(columns={v: k for k, v in p["columns"].items()})[list(p["columns"])]
    require(
        bool(p["column_indices"]),
        "NEEDS_INPUT",
        "Explicit column indices required for Petrel/RMS whitespace ASCII",
    )
    records = []
    for line in path.read_text(encoding="utf-8").splitlines()[p["skiprows"] :]:
        if not line.strip() or line.lstrip().startswith(("#", "--", "!")):
            continue
        row = shlex.split(line)
        require(
            max(p["column_indices"].values()) < len(row), "INVALID_FORMAT", "ASCII row shorter than mapping"
        )
        records.append({name: row[index] for name, index in p["column_indices"].items()})
        require(len(records) <= 1_000_000, "UNSUPPORTED_PROFILE", "ASCII point limit 1M")
    return pd.DataFrame(records)


def import_geodata(context, p, resolved, out):
    require(
        context.get("input_bytes", 0) <= 256 * 1024**2,
        "UNSUPPORTED_PROFILE",
        "Interchange file limit 256 MiB",
    )
    source = out / "source.dat"
    sha = copy_file(context, dict(path=p["path"], file_revision=p["file_revision"]), source)
    scale, sign = (0.3048 if p["length_unit"] == "ft" else 1), (-1 if p["z_direction"] == "down" else 1)
    kind, fmt = p["kind"], p["format"]
    require(
        source.stat().st_size <= 256 * 1024**2,
        "UNSUPPORTED_PROFILE",
        "Interchange point/surface import limit 256 MiB",
    )
    if kind == "surfaces":
        require(
            fmt in ("irap_ascii", "irap_binary", "zmap_ascii", "cps3_ascii"),
            "UNSUPPORTED_FORMAT",
            "Surface format mismatch",
        )
        if fmt in ("irap_binary", "zmap_ascii"):
            header = xtgeo.surface_from_file(source, fformat=fmt, values=False)
            require(header.ncol * header.nrow <= 2_000_000, "UNSUPPORTED_PROFILE", "Surface node limit 2M")
        elif fmt == "irap_ascii":
            with source.open() as stream:
                first = stream.readline().split()
                stream.readline()
                third = stream.readline().split()
            require(
                len(first) >= 2 and third and 0 < int(first[1]) * int(third[0]) <= 2_000_000,
                "UNSUPPORTED_PROFILE",
                "IRAP ASCII node limit 2M",
            )
        surf = cps_surface(source, p) if fmt == "cps3_ascii" else xtgeo.surface_from_file(source, fformat=fmt)
        require(surf.ncol * surf.nrow <= 2_000_000, "UNSUPPORTED_PROFILE", "Surface node limit 2M")
        x, y = surf.get_xy_values()
        values = surf.values
        valid = ~(np.ma.getmaskarray(values) | np.ma.getmaskarray(x) | np.ma.getmaskarray(y))
        table = pd.DataFrame(
            dict(x=np.asarray(x)[valid], y=np.asarray(y)[valid], z=np.asarray(values)[valid])
        )
        table["horizon"] = p["name"]
        # Preserve regular topology/masks for audit; scene is only a preview.
        surf.to_file(out / "surface.gri", fformat="irap_binary")
        extra = {"surface.gri": out / "surface.gri"}
    elif kind == "trajectory" and fmt == "rms_ascii":
        require(p["md_column"] and p["well_id"], "NEEDS_INPUT", "Confirm MD log name and well identifier")
        well = xtgeo.well_from_file(source, fformat="rms_ascii", mdlogname=p["md_column"], strict=True)
        table = well.get_dataframe().rename(
            columns={"X_UTME": "x", "Y_UTMN": "y", "Z_TVDSS": "z", p["md_column"]: "md"}
        )[["x", "y", "z", "md"]]
        table["well_id"] = p["well_id"]
        extra = {}
    elif kind == "polygons" and fmt in ("xyz", "zmap"):
        poly = xtgeo.polygons_from_file(source, fformat=fmt)
        table = poly.get_dataframe().rename(
            columns={poly.xname: "x", poly.yname: "y", poly.zname: "z", poly.pname: "polygon_id"}
        )
        extra = {}
    else:
        require(
            fmt in ("petrel_ascii", "mapped_ascii"),
            "UNSUPPORTED_FORMAT",
            "Format/kind combination unsupported",
        )
        table, extra = ascii_table(source, p), {}
        if kind == "trajectory" and "well_id" not in table and p["well_id"]:
            table["well_id"] = p["well_id"]
    required = {
        "surfaces": {"horizon", "x", "y", "z"},
        "trajectory": {"well_id", "x", "y", "z", "md"},
        "markers": {"well_id", "horizon", "md"},
        "polygons": {"polygon_id", "x", "y", "z"},
    }[kind]
    require(
        required <= set(table),
        "INVALID_FORMAT",
        "Missing canonical columns: " + str(sorted(required - set(table))),
    )
    for name in {"x", "y", "z", "md"} & set(table):
        table[name] = pd.to_numeric(table[name], errors="raise") * scale * (sign if name == "z" else 1)
        require(np.isfinite(table[name]).all(), "INVALID_FORMAT", "Nonfinite coordinate/depth")
    for name in {"well_id", "horizon", "polygon_id"} & set(table):
        table[name] = table[name].astype(str)
    if kind == "trajectory":
        for _, rows in table.groupby("well_id", sort=False):
            require(
                len(rows) >= 2 and (np.diff(rows["md"]) > 0).all(),
                "INVALID_TRAJECTORY",
                "Survey MD must strictly increase within each well",
            )
    if kind == "markers" and not {"x", "y", "z"} <= set(table) and "trajectory" in resolved:
        tracks = pq.read_table(resolved["trajectory"]["paths"]["data.parquet"]).to_pandas()
        for index, row in table.iterrows():
            t = tracks[tracks["well_id"] == row["well_id"]].sort_values("md")
            require(
                len(t) >= 2 and t.md.min() <= row.md <= t.md.max(),
                "INVALID_TRAJECTORY",
                "Marker outside survey MD range",
            )
            for field in ("x", "y", "z"):
                table.loc[index, field] = np.interp(row.md, t.md, t[field])
    if kind == "polygons":
        # XTGeo owns canonical polygon representation even for mapped Petrel ASCII.
        poly = xtgeo.Polygons(
            table.rename(columns={"x": "X_UTME", "y": "Y_UTMN", "z": "Z_TVDSS", "polygon_id": "POLY_ID"})
        )
        for _, rows in poly.get_dataframe().groupby("POLY_ID"):
            require(
                len(rows) >= 4
                and np.allclose(
                    rows.iloc[0][["X_UTME", "Y_UTMN"]].astype(float),
                    rows.iloc[-1][["X_UTME", "Y_UTMN"]].astype(float),
                ),
                "INVALID_POLYGON",
                "Polygon rings must explicitly close",
            )
    require(0 < len(table) <= 2_000_000, "INVALID_FORMAT", "Empty/oversized dataset")
    pq.write_table(pa.Table.from_pandas(table, preserve_index=False), out / "data.parquet")
    reread = pq.read_table(out / "data.parquet").to_pandas()
    require(
        table.equals(reread), "VALIDATION_FAILED", "Published interchange table differs from canonical import"
    )
    report = dict(
        status="PASS",
        operation="geodata_import",
        kind=kind,
        format=fmt,
        rows=len(table),
        source_sha256=sha,
        assumptions=p["assumptions"],
        crs=p["crs"],
        vertical_datum=p["vertical_datum"],
        checks=[
            dict(name="parquet_roundtrip_all_values", status="PASS"),
            dict(name="geological_fit", status="NOT RUN"),
        ],
        limitations=[
            "CPS-3 ASCII requires explicit value order/Y orientation; binary CPS-3 is not supported",
            "ASCII trajectory must contain XYZ/MD; inclination-only survey conversion is not inferred",
        ],
    )
    files = dict(extra, **write_report(out, "Geodata import", report))
    files.update({"data.parquet": out / "data.parquet", "source.dat": source})
    summary = dict(
        kind=kind,
        rows=len(table),
        crs=p["crs"],
        vertical_datum=p["vertical_datum"],
        units={n: "m" for n in ("x", "y", "z", "md") if n in table},
        source_sha256=sha,
        assumptions=p["assumptions"],
        import_validation="PASS",
        z_direction="up",
        report_available=True,
    )
    return "dataset", summary, files
