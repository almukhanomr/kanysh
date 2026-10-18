"""One explicit device policy for Desktop diagnostics and compute entry points.

CUDA imports stay lazy. No scientific default, precision or supported operation changes.
"""

from opensubsurface.errors import require


def cuda_runtime():
    import torch

    available = torch.cuda.is_available()
    return dict(
        cuda_available=available,
        device="cuda" if available else "cpu",
        device_name=torch.cuda.get_device_name(0) if available else None,
        cuda_version=torch.version.cuda,
        torch_version=torch.__version__,
    )


def select_device(policy="cpu", compatible=True, available=None, allow_cpu_fallback=False):
    require(policy in ("cpu", "cuda", "prefer_gpu", "require_gpu"), "INVALID_DEVICE", "Unknown device policy")
    if policy == "cpu":
        return "cpu", []
    available = cuda_runtime()["cuda_available"] if available is None else available
    if compatible and available:
        return "cuda", []
    require(
        policy == "prefer_gpu" and allow_cpu_fallback,
        "NO_COMPATIBLE_GPU",
        "No compatible CUDA path for this operation",
    )
    return "cpu", ["CPU fallback: CUDA unavailable or operation supports CPU only"]
