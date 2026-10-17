"""Large SEG-Y: two bounded passes, sorted regular poststack, float32 Zarr tiles.

No upload size limit, whole cube, trace-header table or random ZIP chunk updates.
Missing traces are explicit NaNs. Unsorted/duplicate traces fail rather than being reordered silently.
"""

import math
import shutil

import numpy as np
import segyio
import zarr

from opensubsurface.adapters.large_grid import check_source
from opensubsurface.adapters.source_files import copy_file
from opensubsurface.errors import require


def import_source(context, p, out):
    require(3600 < context["input_bytes"] <= 1024**4, "UNSUPPORTED_PROFILE", "SEG-Y size must be <=1 TiB")
    require(
        shutil.disk_usage(out).free > context["input_bytes"] * 3.1 + 256 * 1024**2,
        "INSUFFICIENT_DISK",
        "Need SEG-Y working copy and immutable Zarr publication space",
    )
    source = out / "working.segy"
    sha = copy_file(
        context, dict(path=context["manifest_path"], file_revision=context["manifest_revision"]), source
    )
    try:
        summary, files = convert(source, p, out)
    finally:
        source.unlink(missing_ok=True)
    check_source(context)
    summary.update(
        source_sha256=sha,
        source_input_bytes=context["input_bytes"],
        source_revision=context["manifest_revision"],
        storage="seismic-zarr-f32-v1",
    )
    return "seismic", summary, files


def convert(path, p, out):
    tf = segyio.TraceField
    with segyio.open(str(path), "r", ignore_geometry=True, endian=p["endian"]) as f:
        ns, nt = len(f.samples), f.tracecount
        dt = int(f.bin[segyio.BinField.Interval])
        require(
            0 < nt <= 20_000_000 and 0 < ns <= 1_000_000 and dt > 0,
            "UNSUPPORTED_PROFILE",
            "Trace/sample limits or invalid sample interval",
        )
        require(int(f.bin[segyio.BinField.Format]) in (1, 5), "UNSUPPORTED_PROFILE", "IBM/IEEE float32 only")
        measure = int(f.bin[segyio.BinField.MeasurementSystem])
        require(
            measure in (0, 1 if p["coordinate_unit"] == "m" else 2),
            "INVALID_UNITS",
            "Declared coordinates conflict with SEG-Y measurement system",
        )
        ils, xls, delay, previous, ordering = set(), set(), None, None, None
        for n in range(nt):
            h = f.header[n]
            il, xl = h[p["inline_byte"]], h[p["crossline_byte"]]
            require(h[tf.offset] == 0, "UNSUPPORTED_PROFILE", "Zero-offset poststack only")
            require(
                h[tf.TRACE_SAMPLE_COUNT] in (0, ns) and h[tf.TRACE_SAMPLE_INTERVAL] in (0, dt),
                "UNSUPPORTED_PROFILE",
                "Variable trace length/sampling",
            )
            require(h[tf.CoordinateUnits] == 1, "INVALID_UNITS", "Declared length coordinates required")
            if delay is None:
                delay = h[tf.DelayRecordingTime]
            require(h[tf.DelayRecordingTime] == delay, "UNSUPPORTED_PROFILE", "Variable trace origin")
            if previous is not None:
                if ordering is None:
                    ordering = (
                        "inline" if previous[0] == il else "crossline" if previous[1] == xl else "inline"
                    )
                before = previous if ordering == "inline" else previous[::-1]
                current = (il, xl) if ordering == "inline" else (xl, il)
                require(
                    current > before, "AMBIGUOUS_GEOMETRY", "Traces must be sorted; duplicate/unordered trace"
                )
            previous = (il, xl)
            ils.add(il)
            xls.add(xl)
            require(
                len(ils) <= 100000 and len(xls) <= 100000, "UNSUPPORTED_PROFILE", "Axis metadata limit 100000"
            )
        ils, xls = np.array(sorted(ils)), np.array(sorted(xls))
        require(len(ils) > 1 and len(xls) > 1, "AMBIGUOUS_GEOMETRY", "Need 3D inline/crossline mapping")
        require(
            np.all(np.diff(ils) == np.diff(ils)[0]) and np.all(np.diff(xls) == np.diff(xls)[0]),
            "UNSUPPORTED_PROFILE",
            "Regular inline/crossline axes required",
        )
        # Store outer/inner order matching source, so each compressed chunk is written once.
        outer, inner = (ils, xls) if ordering == "inline" else (xls, ils)
        tile = max(1, min(32, (8 * 1024**2) // (ns * 4), len(inner)))
        chunks = len(outer) * math.ceil(len(inner) / tile)
        require(
            chunks <= 200000 and len(outer) * len(inner) * ns * 4 <= 1024**4,
            "UNSUPPORTED_PROFILE",
            "Cube/chunk metadata budget exceeded",
        )
        require(
            shutil.disk_usage(out).free > len(outer) * len(inner) * (ns * 4 + 16) * 2.1 + 64 * 1024**2,
            "INSUFFICIENT_DISK",
            "Need uncompressed cube plus immutable copy; no assumed compression",
        )
        path = out / "cube.zip"
        scale_m = 0.3048 if p["coordinate_unit"] == "ft" else 1.0
        finite_samples, sum_squares, amplitude_min, amplitude_max = 0, 0.0, np.inf, -np.inf
        canonical_shape = (len(ils), len(xls), ns)
        canonical_chunks = (1, tile, ns) if ordering == "inline" else (tile, 1, ns)
        with zarr.ZipStore(str(path), mode="w") as store:
            group = zarr.group(store=store)
            group.attrs.update(
                storage="seismic-zarr-f32-v1",
                axis_order=["inline", "crossline", "sample"],
                source_order=ordering,
            )
            cube = group.create_dataset(
                "amplitude", shape=canonical_shape, chunks=canonical_chunks, dtype="f4", fill_value=np.nan
            )
            x = group.create_dataset(
                "x", shape=canonical_shape[:2], chunks=canonical_chunks[:2], dtype="f8", fill_value=np.nan
            )
            y = group.create_dataset(
                "y", shape=canonical_shape[:2], chunks=canonical_chunks[:2], dtype="f8", fill_value=np.nan
            )
            n = 0
            for i, o in enumerate(outer):
                for start in range(0, len(inner), tile):
                    stop = min(start + tile, len(inner))
                    data = np.full((stop - start, ns), np.nan, np.float32)
                    xy = np.full((stop - start, 2), np.nan)
                    for j in range(start, stop):
                        if n >= nt:
                            break
                        h = f.header[n]
                        oi, ji = (
                            (h[p["inline_byte"]], h[p["crossline_byte"]])
                            if ordering == "inline"
                            else (h[p["crossline_byte"]], h[p["inline_byte"]])
                        )
                        if (oi, ji) != (o, inner[j]):
                            continue
                        trace = np.array(f.trace[n], dtype=np.float32, copy=True)
                        require(np.isfinite(trace).all(), "QC_FAILED", "Nonfinite amplitudes in source trace")
                        data[j - start] = trace
                        scalar = h[tf.SourceGroupScalar]
                        scalar = scalar if scalar > 0 else 1 / abs(scalar) if scalar < 0 else 1
                        xy[j - start] = np.array([h[tf.CDP_X], h[tf.CDP_Y]]) * scalar * scale_m
                        finite_samples += ns
                        sum_squares += float(np.dot(trace.astype(np.float64), trace.astype(np.float64)))
                        amplitude_min = min(amplitude_min, float(trace.min()))
                        amplitude_max = max(amplitude_max, float(trace.max()))
                        n += 1
                    if ordering == "inline":
                        cube[i, start:stop, :] = data
                        x[i, start:stop], y[i, start:stop] = xy[:, 0], xy[:, 1]
                    else:
                        cube[start:stop, i, :] = data
                        x[start:stop, i], y[start:stop, i] = xy[:, 0], xy[:, 1]
            require(n == nt, "GRID_MAPPING_ERROR", "Trace count/mapping mismatch")
            samples = np.asarray(f.samples, dtype=np.float64)
            if p["domain"] == "twt":
                samples /= 1000
            for key, values in {"inline": ils, "crossline": xls, "sample": samples}.items():
                group.create_dataset(key, data=values)
        summary = dict(
            shape=list(canonical_shape),
            domain=p["domain"],
            sample_unit="s" if p["domain"] == "twt" else "m",
            axis_order=["inline", "crossline", "sample"],
            source_order=ordering,
            crs=p["crs"],
            vertical_datum=p["vertical_datum"],
            geometry_unit="m",
            missing_traces=len(outer) * len(inner) - nt,
            traces=nt,
            samples=finite_samples,
            dtype="float32",
            chunks=list(canonical_chunks),
            qc_status="PASS",
            endian=p["endian"],
            amplitude_min=amplitude_min,
            amplitude_max=amplitude_max,
            amplitude_rms=math.sqrt(sum_squares / finite_samples),
            working_trace_buffer_bytes=tile * ns * 4,
            source="SEG-Y sorted regular zero-offset poststack; explicit missing-trace NaNs",
        )
        return summary, {"cube.zip": path}
