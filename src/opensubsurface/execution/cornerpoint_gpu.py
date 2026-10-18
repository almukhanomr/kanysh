"""VRAM-bounded float64 tetra6 CUDA kernel with mandatory CPU validation."""

import numpy as np

from opensubsurface.calculations.validation import ATOL, RTOL
from opensubsurface.errors import require


def cell_volumes(corners, contact=None):
    import torch

    from opensubsurface.adapters.cornerpoint import TETS
    from opensubsurface.adapters.cornerpoint import cell_volumes as cpu_volumes

    require(
        torch.cuda.is_available(),
        "NO_COMPATIBLE_GPU",
        "CUDA tetra6 requires an available NVIDIA device",
        "execution.device_policy",
        "Use execution.device_policy='cpu' or install the CUDA runtime",
    )
    if len(corners) == 0:
        return np.zeros(0, dtype=np.float64)
    free, _ = torch.cuda.mem_get_info()
    step = min(len(corners), 16384, max(1, int(free * 0.25) // (192 * 32)))
    require(
        free >= 16 * 1024**2,
        "INSUFFICIENT_MEMORY",
        "Insufficient free VRAM for tetra6",
        "execution.device_policy",
        "Close GPU applications or select CPU",
    )

    def volume(t):
        return (
            torch.abs(
                torch.sum(
                    (t[:, 1] - t[:, 0]) * torch.linalg.cross(t[:, 2] - t[:, 0], t[:, 3] - t[:, 0]), dim=1
                )
            )
            / 6
        )

    def clipped(t):
        inside = t[:, :, 2] >= contact
        counts = inside.sum(dim=1)
        result = torch.zeros(len(t), dtype=torch.float64, device="cuda")
        full = counts == 4
        result[full] = volume(t[full])
        for n in (1, 2, 3):
            mask = counts == n
            a = t[mask]
            if not len(a):
                continue
            order = torch.argsort((~inside[mask]).to(torch.int32), dim=1, stable=True)
            a = torch.gather(a, 1, order[:, :, None].expand(-1, -1, 3))
            if n in (1, 3):
                if n == 3:
                    a = a[:, [3, 0, 1, 2]]
                ratio = (contact - a[:, 0, 2, None]) / (a[:, 1:, 2] - a[:, 0, 2, None])
                whole = volume(a)
                small = whole * torch.prod(ratio, dim=1)
                result[mask] = small if n == 1 else whole - small
            else:

                def edge(i, j):
                    ratio = (contact - a[:, i, 2]) / (a[:, j, 2] - a[:, i, 2])
                    return a[:, i] + ratio[:, None] * (a[:, j] - a[:, i])

                ac, ad, bc, bd = edge(0, 2), edge(0, 3), edge(1, 2), edge(1, 3)
                result[mask] = (
                    volume(torch.stack((a[:, 0], a[:, 1], ac, ad), dim=1))
                    + volume(torch.stack((a[:, 1], ac, ad, bd), dim=1))
                    + volume(torch.stack((a[:, 1], ac, bc, bd), dim=1))
                )
        return result

    result = np.empty(len(corners), dtype=np.float64)
    try:
        with torch.no_grad():
            for start in range(0, len(corners), step):
                c = torch.as_tensor(
                    np.ascontiguousarray(corners[start : start + step]), dtype=torch.float64, device="cuda"
                )
                value = torch.zeros(len(c), dtype=torch.float64, device="cuda")
                for tet in TETS:
                    vertices = c[:, tet.tolist()]
                    value += volume(vertices) if contact is None else clipped(vertices)
                result[start : start + step] = value.cpu().numpy()
    except torch.cuda.OutOfMemoryError as error:
        from opensubsurface.errors import DomainError

        raise DomainError(
            "INSUFFICIENT_MEMORY",
            "CUDA tetra6 allocation failed",
            "execution.device_policy",
            "Free VRAM or select CPU; no fallback was performed",
        ) from error
    expected = cpu_volumes(corners, contact)
    require(
        np.allclose(result, expected, rtol=RTOL, atol=ATOL),
        "VALIDATION_FAILED",
        "CUDA tetra6 differs from the CPU float64 reference",
        "execution.device_policy",
        "Inspect geometry and CUDA runtime; a mismatching GPU result cannot be published",
        dict(max_absolute_difference=float(np.max(np.abs(result - expected), initial=0))),
    )
    return result
