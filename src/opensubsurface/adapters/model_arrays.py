"""One bounded block interface for immutable small, Cartesian and corner-point models."""

from contextlib import contextmanager

import numpy as np

from opensubsurface.adapters.large_grid import blocks, is_large, open_grid
from opensubsurface.errors import require


def ijk(ids, shape, order):
    if order == "ECLIPSE":
        return np.column_stack((ids % shape[0], (ids // shape[0]) % shape[1], ids // (shape[0] * shape[1])))
    return np.column_stack(np.unravel_index(ids, tuple(shape), order="C"))


def cartesian_corners(obj, ids, order):
    shape = obj["summary"]["grid"]["shape"]
    extent = np.array(obj["summary"]["grid"]["extent"])
    step = (extent[1::2] - extent[::2]) / shape
    indices = ijk(ids, shape, order)
    if order == "ECLIPSE":
        indices[:, 2] = shape[2] - 1 - indices[:, 2]
    offsets = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]]
    )
    return extent[::2] + (indices[:, None, :] + offsets) * step


@contextmanager
def opened(obj):
    if is_large(obj):
        with open_grid(obj) as group:
            yield group, group.attrs["order"]
    else:
        with np.load(obj["paths"]["arrays.npz"], allow_pickle=False) as arrays:
            yield {k: arrays[k].ravel() for k in arrays.files}, "C"


def iterate(obj, include_corners=True):
    with opened(obj) as (group, order):
        if is_large(obj):
            for start, data in blocks(group):
                if include_corners and "corners" not in data:
                    data["corners"] = cartesian_corners(
                        obj, np.arange(start, start + len(data["active"])), order
                    )
                yield start, data, order
        else:
            for start in range(0, len(group["active"]), 16384):
                data = {k: a[start : start + 16384] for k, a in group.items()}
                if include_corners:
                    data["corners"] = cartesian_corners(
                        obj, np.arange(start, start + len(data["active"])), order
                    )
                yield start, data, order


def region(data, field):
    require(field in data, "MISSING_REGION", "Region definition missing: " + field)
    values = np.asarray(data[field])
    require(
        np.isfinite(values).all() and (values == np.floor(values)).all(),
        "INVALID_REGION",
        "Finite integer regions required",
    )
    return values.astype(np.int64)


def provenance(obj):
    return dict(
        id=obj["id"],
        revision=obj["revision"],
        content_hash=obj["content_hash"],
        grid=obj["summary"].get("grid"),
        crs=obj["summary"].get("crs"),
        vertical_datum=obj["summary"].get("vertical_datum"),
    )
