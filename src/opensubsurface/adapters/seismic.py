import numpy as np
import zarr

from opensubsurface.errors import require


def write_volume(out, cube, geometry):
    path = out / "cube.zip"
    with zarr.ZipStore(str(path), mode="w") as store:
        group = zarr.group(store=store)
        group.create_dataset("amplitude", data=cube, chunks=(1, min(16, cube.shape[1]), cube.shape[2]))
        for key, value in geometry.items():
            group.create_dataset(key, data=np.asarray(value))
    return path


def generate(p, out):
    ni, nj, ns = p["shape"]
    dt = p["dt_seconds"]
    t = np.arange(ns) * dt
    rng = np.random.default_rng(p["seed"])
    i, j = np.meshgrid(np.arange(ni), np.arange(nj), indexing="ij")
    center = 0.18 + 0.002 * i + 0.001 * j
    a = (np.pi * 25 * (t[None, None, :] - center[..., None])) ** 2
    cube = (1 - 2 * a) * np.exp(-a) + rng.normal(0, 0.025, (ni, nj, ns))
    path = write_volume(
        out,
        cube,
        {"inline": np.arange(ni), "crossline": np.arange(nj), "sample": t, "x": i * 25.0, "y": j * 25.0},
    )
    return (
        "seismic",
        dict(
            shape=[ni, nj, ns],
            domain="twt",
            sample_unit="s",
            dt_seconds=dt,
            crs="LOCAL_METRIC",
            vertical_datum="SYNTHETIC_ORIGIN",
            geometry_unit="m",
            provenance="Синтетический Ricker 25 Hz; Apache-2.0 generator; seed fixed",
            velocity_m_s=p["velocity_m_s"],
        ),
        {"cube.zip": path},
    )


def import_segy(path, p, out):
    import segyio

    from opensubsurface.adapters.imports import check_coordinates

    check_coordinates(p["crs"], p["vertical_datum"])
    canonical = out / "cube.zip"
    with segyio.open(str(path), "r", ignore_geometry=True, endian=p["endian"]) as f:
        require(
            int(f.bin[segyio.BinField.Format]) in (1, 5),
            "UNSUPPORTED_PROFILE",
            "Подтверждённый профиль: IBM/IEEE float32 SEG-Y",
        )
        require(
            np.all(np.asarray(f.attributes(segyio.TraceField.offset)[:]) == 0),
            "UNSUPPORTED_PROFILE",
            "Поддерживается только zero-offset poststack; ненулевые offsets",
        )
        il = np.array(f.attributes(p["inline_byte"])[:])
        xl = np.array(f.attributes(p["crossline_byte"])[:])
        ils, xls = np.unique(il), np.unique(xl)
        require(
            len(ils) > 1 and len(xls) > 1, "AMBIGUOUS_GEOMETRY", "Проверьте inline/crossline header mapping"
        )
        require(
            len(set(zip(il.tolist(), xl.tolist()))) == len(il),
            "AMBIGUOUS_GEOMETRY",
            "Дубли trace geometry; задайте явное правило",
        )
        require(
            len(ils) * len(xls) * len(f.samples) <= 50_000_000,
            "INSUFFICIENT_MEMORY",
            "Профиль ограничен 50 млн samples; автоматическое уменьшение запрещено",
        )
        require(
            np.all(np.diff(ils) == np.diff(ils)[0]) and np.all(np.diff(xls) == np.diff(xls)[0]),
            "UNSUPPORTED_PROFILE",
            "Нерегулярная геометрия",
        )
        ns = len(f.samples)
        dt = int(f.bin[segyio.BinField.Interval])
        delays = np.array(f.attributes(segyio.TraceField.DelayRecordingTime)[:])
        require(len(set(delays)) == 1, "UNSUPPORTED_PROFILE", "Variable trace origin не поддерживается")
        with zarr.ZipStore(str(canonical), mode="w") as store:
            group = zarr.group(store=store)
            cube = group.create_dataset(
                "amplitude", shape=(len(ils), len(xls), ns), dtype="f8", chunks=(1, 1, ns), fill_value=np.nan
            )
            xs = np.full((len(ils), len(xls)), np.nan)
            ys = xs.copy()
            imap, jmap = {v: i for i, v in enumerate(ils)}, {v: i for i, v in enumerate(xls)}
            for n in range(f.tracecount):
                header = f.header[n]
                require(
                    header[segyio.TraceField.TRACE_SAMPLE_COUNT] in (0, ns),
                    "UNSUPPORTED_PROFILE",
                    "Variable trace length",
                )
                require(
                    header[segyio.TraceField.TRACE_SAMPLE_INTERVAL] in (0, dt),
                    "UNSUPPORTED_PROFILE",
                    "Variable sampling",
                )
                require(
                    header[segyio.TraceField.CoordinateUnits] == 1,
                    "INVALID_UNITS",
                    "Поддерживаются только declared length coordinates",
                )
                scalar = header[segyio.TraceField.SourceGroupScalar]
                scale = scalar if scalar > 0 else (1 / abs(scalar) if scalar < 0 else 1)
                i, j = imap[il[n]], jmap[xl[n]]
                cube[i, j, :] = f.trace[n].astype(np.float64)
                xs[i, j] = header[segyio.TraceField.CDP_X] * scale
                ys[i, j] = header[segyio.TraceField.CDP_Y] * scale
            samples = np.asarray(f.samples, float)
            if p["domain"] == "twt":
                samples /= 1000
            for key, values in {"inline": ils, "crossline": xls, "sample": samples, "x": xs, "y": ys}.items():
                group.create_dataset(key, data=values)
    return (
        "seismic",
        dict(
            shape=[len(ils), len(xls), ns],
            domain=p["domain"],
            sample_unit="s" if p["domain"] == "twt" else "m",
            crs=p["crs"],
            vertical_datum=p["vertical_datum"],
            geometry_unit="m",
            missing_traces=int(len(ils) * len(xls) - len(il)),
            endian=p["endian"],
            source="SEG-Y; missing traces masked with NaN",
        ),
        {"cube.zip": canonical, "source.segy": path},
    )


def open_volume(path):
    store = zarr.ZipStore(str(path), mode="r")
    return store, zarr.open_group(store, mode="r")


def read_section(group, axis, index, max_samples=4_000_000):
    shape = group["amplitude"].shape
    require(0 <= axis < 3 and 0 <= index < shape[axis], "QC_FAILED", "Индекс вне куба")
    require(
        int(np.prod([n for i, n in enumerate(shape) if i != axis])) <= max_samples,
        "VIEW_TOO_LARGE",
        "Срез превышает 4 млн отсчётов; используйте scene_show со stride для ограниченного превью",
    )
    selection = [slice(None)] * 3
    selection[axis] = index
    return np.asarray(group["amplitude"][tuple(selection)])
