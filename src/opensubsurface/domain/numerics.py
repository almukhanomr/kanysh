"""Научные конвенции: (x,y,z), Z-up; OPM I-fast, J-next, K-down."""

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import hilbert

from opensubsurface.errors import require

PROPERTY_BOUNDS = {"phi": (0, 1), "ntg": (0, 1), "sw": (0, 1), "permeability_md": (0, np.inf)}


def grid_arrays(grid):
    shape = tuple(grid["shape"])
    e = grid["extent"]
    spacing = np.array([(e[2 * i + 1] - e[2 * i]) / shape[i] for i in range(3)])
    axes = [e[2 * i] + (np.arange(shape[i]) + 0.5) * spacing[i] for i in range(3)]
    centers = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
    return centers, spacing


def validate_properties(arrays):
    active = arrays["active"].astype(bool)
    require(active.any(), "QC_FAILED", "Нет активных ячеек")
    for name, (low, high) in PROPERTY_BOUNDS.items():
        values = arrays[name]
        require(values.shape == active.shape, "QC_FAILED", f"Размер {name} не совпадает с сеткой")
        require(np.isfinite(values[active]).all(), "QC_FAILED", f"Пропуски/NaN/Inf в активной области {name}")
        require(
            ((values[active] >= low) & (values[active] <= high)).all(),
            "QC_FAILED",
            f"{name} вне физических границ",
        )


def volumes(arrays, grid, zone_ids, contact_z_m, bo, device="cpu", precision="float64"):
    require(np.isfinite(bo) and bo > 0, "QC_FAILED", "Bo должен быть положительным")
    require(np.isfinite(contact_z_m), "QC_FAILED", "OWC должен быть конечным")
    validate_properties(arrays)
    centers, spacing = grid_arrays(grid)
    mask = arrays["active"].astype(bool) & np.isin(arrays["zones"], zone_ids)
    require(mask.any(), "QC_FAILED", "Выбранные зоны не содержат активных ячеек")
    cell_volume = float(np.prod(spacing))
    # Cell top minus OWC, clipped to cell thickness; center membership only for zone IDs.
    fraction = np.clip((centers[..., 2] + spacing[2] / 2 - contact_z_m) / spacing[2], 0, 1)
    if device == "cuda":
        import torch

        dtype = torch.float64 if precision == "float64" else torch.float32

        def tensor(a):
            return torch.as_tensor(a, device="cuda", dtype=dtype)

        m, f = tensor(mask), tensor(fraction)
        ntg, phi, sw = (tensor(np.where(mask, arrays[k], 0)) for k in ("ntg", "phi", "sw"))
        torch.cuda.synchronize()
        sums = [
            m.sum(),
            (m * f).sum(),
            (m * f * ntg).sum(),
            (m * f * ntg * phi).sum(),
            (m * f * ntg * phi * (1 - sw)).sum(),
        ]
        result = [float(x.item()) * cell_volume for x in sums]
        torch.cuda.synchronize()
    else:
        # Mask before multiplication: NaN outside active cells never poisons the sum.
        f = fraction[mask]
        ntg, phi, sw = (arrays[k][mask] for k in ("ntg", "phi", "sw"))
        result = [
            mask.sum() * cell_volume,
            f.sum() * cell_volume,
            (f * ntg).sum() * cell_volume,
            (f * ntg * phi).sum() * cell_volume,
            (f * ntg * phi * (1 - sw)).sum() * cell_volume,
        ]
    names = ["GRV", "GRV_oil_interval", "NetRockVolume", "PV", "HCPV"]
    out = dict(zip(names, map(float, result)))
    out["STOIIP"] = out["HCPV"] / bo
    return {
        "values": out,
        "units": {k: ("standard_m3" if k == "STOIIP" else "m3") for k in out},
        "bo": bo,
        "contact_z_m": contact_z_m,
        "backend": device,
        "precision": precision,
        "assumptions": [
            "Нефть–вода; горизонтальный OWC; без капиллярной переходной зоны",
            "Начальный объём нефти, не извлекаемые запасы",
            "Zone membership по центру; OWC пересекает ячейку дробно",
        ],
        "vertical_cell_step_m": float(spacing[2]),
        "boundary_discretization": "Ошибка геологической границы до одного шага сетки",
    }


def quantiles(values):
    v = np.asarray(values, dtype=float)
    require(v.size > 0 and np.isfinite(v).all(), "QC_FAILED", "Недопустимая выборка статистики")
    q10, q50, q90 = np.quantile(v, [0.1, 0.5, 0.9], method="linear")
    return dict(
        min=float(v.min()),
        max=float(v.max()),
        mean=float(v.mean()),
        std=float(v.std(ddof=0)),
        Q10=float(q10),
        Q50=float(q50),
        Q90=float(q90),
        P90=float(q10),
        P50=float(q50),
        P10=float(q90),
        method="linear",
        convention="P — вероятность превышения; P90=Q10",
    )


def seismic_attribute(cube, kind, window=9, device="cpu"):
    cube = np.asarray(cube, dtype=np.float64)
    require(cube.shape[-1] >= 3, "QC_FAILED", "Слишком короткая trace")
    require(window <= cube.shape[-1] and window % 2 == 1, "QC_FAILED", "Недопустимое окно")
    # A trace with any missing samples is masked in full for both CPU and GPU.
    valid = np.isfinite(cube).all(axis=-1, keepdims=True)
    clean = np.where(valid, cube, 0)
    if device == "cuda":
        import torch
        import torch.nn.functional as f

        x = torch.as_tensor(clean, device="cuda", dtype=torch.float64)
        if kind == "rms":
            flat = x.reshape(-1, 1, x.shape[-1])
            padded = f.pad(flat * flat, (window // 2, window // 2), mode="replicate")
            y = torch.sqrt(f.avg_pool1d(padded, window, stride=1)).reshape(x.shape)
        else:
            n = x.shape[-1]
            h = torch.zeros(n, dtype=x.dtype, device=x.device)
            h[0] = 1
            h[1 : (n + 1) // 2] = 2
            if n % 2 == 0:
                h[n // 2] = 1
            y = torch.abs(torch.fft.ifft(torch.fft.fft(x, dim=-1) * h, dim=-1))
        torch.cuda.synchronize()
        out = y.cpu().numpy()
    elif kind == "rms":
        out = np.sqrt(np.maximum(uniform_filter1d(clean**2, size=window, axis=-1, mode="nearest"), 0))
    else:
        out = np.abs(hilbert(clean, axis=-1))
    return np.where(valid, out, np.nan)


def time_to_z(twt_seconds, velocity_m_s, origin_z_m):
    require(velocity_m_s > 0, "QC_FAILED", "Скорость должна быть положительной")
    return origin_z_m - velocity_m_s * np.asarray(twt_seconds) / 2


def z_to_time(z, velocity_m_s, origin_z_m):
    return 2 * (origin_z_m - np.asarray(z)) / velocity_m_s


def to_opm(array):
    """Input (nx,ny,nz) z ascending; OPM i-fast and k depth-down."""
    return np.asarray(array)[:, :, ::-1].ravel(order="F")


def from_opm(values, shape, active=None):
    flat = np.asarray(values)
    if active is not None and len(flat) == np.count_nonzero(active):
        expanded = np.full(int(np.prod(shape)), np.nan)
        expanded[to_opm(active).astype(bool)] = flat
        flat = expanded
    require(flat.size == np.prod(shape), "GRID_MAPPING_ERROR", "Число result cells не совпадает")
    return flat.reshape(shape, order="F")[:, :, ::-1]


def water_cut(oil, water):
    oil, water = np.asarray(oil, float), np.asarray(water, float)
    total = oil + water
    return np.divide(water, total, out=np.full_like(total, np.nan), where=total > 0)


def table_time_to_z(twt_seconds, table, origin_z_m):
    table = np.asarray(table, float)
    values = np.asarray(twt_seconds, float)
    require(
        np.all((values >= table[0, 0]) & (values <= table[-1, 0])),
        "QC_FAILED",
        "TWT вне time-depth table; extrapolation запрещена",
    )
    return origin_z_m - np.interp(values, table[:, 0], table[:, 1])


def table_z_to_time(z, table, origin_z_m):
    table = np.asarray(table, float)
    values = origin_z_m - np.asarray(z, float)
    require(
        np.all((values >= table[0, 1]) & (values <= table[-1, 1])),
        "QC_FAILED",
        "Глубина вне time-depth table; extrapolation запрещена",
    )
    return np.interp(values, table[:, 1], table[:, 0])
