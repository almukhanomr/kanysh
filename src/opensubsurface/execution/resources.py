"""Conservative resource estimates; never change scientific inputs to fit a machine."""

import os
import shutil

import psutil

from opensubsurface.errors import require

MIB = 1024**2
PROCESS_BYTES = 256 * MIB
# Measured (tracemalloc, 262 144-cell corner-point block): geometry flags peak ~0.7 KiB/cell, volumes
# ~0.6, independent integral ~0.3, plus the block itself and per-region copies: ~1.5-2 KiB/cell.
# Twice that is budgeted. This is a resource estimate only; no scientific input depends on it.
BYTES_PER_CELL = 4096


def memory_check(required, field="execution.max_workers", available=None):
    available = psutil.virtual_memory().available if available is None else available
    require(
        required <= available * 0.5,
        "INSUFFICIENT_MEMORY",
        f"Estimated working memory {required:,} bytes exceeds 50% of available RAM ({available:,})",
        field,
        "Reduce execution.max_workers, close other applications, or use a host with more RAM",
        dict(required_bytes=int(required), available_bytes=int(available), budget_fraction=0.5),
    )


def disk_check(path, required):
    free = shutil.disk_usage(path).free
    require(
        required <= free * 0.9,
        "INSUFFICIENT_DISK",
        f"Need {required:,} bytes of working/publication space; {free:,} bytes free",
        "path",
        "Free disk space in the workspace/home or choose a larger volume",
        dict(required_bytes=int(required), free_bytes=int(free)),
    )


def plan(cells, block_cells=16384, max_workers=None, fixed_bytes=0):
    per_worker = PROCESS_BYTES + block_cells * BYTES_PER_CELL
    budget = int(psutil.virtual_memory().available * 0.5)
    blocks = max(1, (cells + block_cells - 1) // block_cells)
    platform_limit = 61 if os.name == "nt" else 256
    recommended = max(
        1, min(os.cpu_count() or 1, platform_limit, blocks, (budget - fixed_bytes) // per_worker - 1)
    )
    workers = recommended if max_workers is None else min(max_workers, platform_limit, blocks)
    # Parallel: N workers plus the coordinator. One worker runs in-process (no child, no coordinator copy).
    required = fixed_bytes + (workers + 1 if workers > 1 else 1) * per_worker
    memory_check(required)
    return dict(
        max_workers=workers,
        block_cells=block_cells,
        estimated_peak_bytes=required,
        memory_budget_bytes=budget,
        reduction_order="ascending immutable block offset",
    )


def inventory(home):
    ram = psutil.virtual_memory()
    per_worker = PROCESS_BYTES + 16384 * BYTES_PER_CELL
    result = dict(
        logical_cores=os.cpu_count() or 1,
        physical_cores=psutil.cpu_count(logical=False),
        ram_total_bytes=ram.total,
        ram_available_bytes=ram.available,
        home_disk_free_bytes=shutil.disk_usage(home).free,
        recommended_max_workers=max(
            1,
            min(
                os.cpu_count() or 1,
                61 if os.name == "nt" else 256,
                int(ram.available * 0.5) // per_worker - 1,
            ),
        ),
        recommended_block_cells=16384,
        vram_status="NOT PROBED",
    )
    # Diagnostics must not import torch just to enumerate CPU resources.
    import sys

    if "torch" in sys.modules:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            result.update(vram_status="AVAILABLE", vram_free_bytes=free, vram_total_bytes=total)
        else:
            result["vram_status"] = "UNAVAILABLE"
    return result
