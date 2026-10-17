"""Bounded, immutable PyVista scene exported with trame's offline VTK.js viewer."""

import json

import numpy as np
import pyarrow.parquet as pq

from opensubsurface.errors import require


def _selected(indices, item):
    mask = indices % item["stride"] == 0
    if item["cell_range"]:
        a, b = item["cell_range"]
        mask &= (indices >= a) & (indices < b)
    return mask


def grid_geometry(obj, item, budget):
    """Return selected true cell corners; previews never alter calculation artifacts."""
    from opensubsurface.adapters.large_grid import blocks, is_large, open_grid

    shape, e = obj["summary"]["grid"]["shape"], obj["summary"]["grid"]["extent"]
    geometry, values, indices, total = [], [], [], 0

    def take(start, data, order):
        nonlocal total
        ids = np.arange(start, start + len(data["active"]))
        mask = data["active"].astype(bool) & _selected(ids, item)
        count = int(mask.sum())
        total += count
        require(total <= budget, "VIEW_TOO_LARGE", "Increase stride or narrow cell_range for 3D preview")
        if not count:
            return
        ids = ids[mask]
        if "corners" in data:
            corners = data["corners"][mask]
        else:
            spacing = (np.array(e)[1::2] - np.array(e)[::2]) / shape
            if order == "ECLIPSE":
                ijk = np.column_stack(
                    [
                        ids % shape[0],
                        (ids // shape[0]) % shape[1],
                        shape[2] - 1 - ids // (shape[0] * shape[1]),
                    ]
                )
            else:
                ijk = np.column_stack(np.unravel_index(ids, shape, order="C"))
            offsets = np.array(
                [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]]
            )
            corners = np.array(e)[::2] + (ijk[:, None, :] + offsets) * spacing
        geometry.append(corners)
        require(item["field"] in data, "INVALID_SCENE", "Selected grid property missing")
        values.append(data[item["field"]][mask])
        indices.append(ids)

    if is_large(obj):
        with open_grid(obj) as group:
            for start, data in blocks(group):
                take(start, data, group.attrs["order"])
    else:
        with np.load(obj["paths"]["arrays.npz"], allow_pickle=False) as data:
            flat = {k: data[k].ravel() for k in data.files}
            for start in range(0, len(flat["active"]), 16384):
                take(start, {k: v[start : start + 16384] for k, v in flat.items()}, "C")
    require(total > 0, "INVALID_SCENE", "No cells selected for display")
    return np.concatenate(geometry), np.concatenate(values), np.concatenate(indices)


def seismic_geometry(obj, item, budget):
    from opensubsurface.adapters.seismic import open_volume

    store, g = open_volume(obj["paths"]["cube.zip"])
    try:
        shape = g["amplitude"].shape
        axis, index = {"inline": 0, "crossline": 1, "sample": 2}[item["seismic_axis"]], item["slice_index"]
        require(index < shape[axis], "INVALID_SCENE", "Seismic slice outside cube")
        selection = [slice(None, None, item["stride"])] * 3
        selection[axis] = index
        expected = int(np.prod([len(range(0, n, item["stride"])) for i, n in enumerate(shape) if i != axis]))
        require(expected <= budget, "VIEW_TOO_LARGE", "Increase seismic stride")
        samples = np.asarray(g["sample"][:])
        z = samples
        if obj["summary"]["domain"] == "twt":
            require(
                item["velocity_m_s"] is not None and item["origin_z_m"] is not None,
                "MISSING_VELOCITY",
                "TWT overlay needs explicit velocity_m_s and origin_z_m",
            )
            z = item["origin_z_m"] - samples * item["velocity_m_s"] / 2
        else:
            z = -samples
        data = np.asarray(g["amplitude"][tuple(selection)])
        spatial = tuple(selection[:2])
        x, y = np.asarray(g["x"][spatial]), np.asarray(g["y"][spatial])
        if axis == 2:
            z = np.full(x.shape, z[index])
        else:
            z = z[:: item["stride"]]
            x, y, z = np.broadcast_arrays(x[:, None], y[:, None], z[None, :])
        return np.stack([x, y, z], axis=-1), data
    finally:
        store.close()


def export_scene(scene, objects, p, out):
    try:
        import pyvista as pv
    except ImportError:
        require(False, "MISSING_DEPENDENCY", "Install kanysh-basic[viewer]")

    visible = [(key, item) for key, item in scene.items() if item["visible"]]
    require(bool(visible), "INVALID_SCENE", "No visible objects")
    scales = {item["vertical_exaggeration"] for _, item in visible}
    require(len(scales) == 1, "INVALID_SCENE", "Use one vertical exaggeration for the entire scene")
    plotter = pv.Plotter(off_screen=True, window_size=(1200, 800))
    plotter.set_background("#102333", top="#203f4d")
    cell_count, point_count, evidence = 0, 0, []
    try:
        for key, item in visible:
            obj = objects[key]
            record = dict(ref=item["ref"], kind=obj["kind"], content_hash=obj["content_hash"], options=item)
            common = dict(
                opacity=item["opacity"], name=key, show_scalar_bar=True, scalar_bar_args=dict(color="#e4eef2")
            )
            if obj["kind"] in ("model", "properties"):
                corners, values, ids = grid_geometry(obj, item, p["max_cells"] - cell_count)
                points = corners[:, [0, 1, 3, 2, 4, 5, 7, 6]].reshape(-1, 3)
                connectivity = np.column_stack(
                    [np.full(len(corners), 8), np.arange(len(points)).reshape(-1, 8)]
                ).ravel()
                mesh = pv.UnstructuredGrid(
                    connectivity, np.full(len(corners), pv.CellType.HEXAHEDRON), points
                )
                mesh.cell_data[item["field"]] = values
                mesh.cell_data["source_cell_id"] = ids
                plotter.add_mesh(
                    mesh,
                    scalars=item["field"],
                    show_edges=item["selected"],
                    edge_color="#ffffff",
                    cmap="viridis",
                    **common,
                )
                cell_count += len(corners)
                record.update(
                    displayed_cells=len(corners), total_cells=int(np.prod(obj["summary"]["grid"]["shape"]))
                )
            elif obj["kind"] == "seismic":
                points, values = seismic_geometry(obj, item, p["max_points"] - point_count)
                mesh = pv.StructuredGrid(points[..., 0], points[..., 1], points[..., 2])
                mesh.point_data["amplitude"] = values.ravel(order="F")
                plotter.add_mesh(mesh, scalars="amplitude", cmap="gray", **common)
                point_count += values.size
                record.update(
                    displayed_samples=int(values.size),
                    domain=obj["summary"]["domain"],
                    velocity_m_s=item["velocity_m_s"],
                    origin_z_m=item["origin_z_m"],
                )
            elif obj["kind"] == "dataset":
                table = pq.read_table(obj["paths"]["data.parquet"]).to_pandas()
                kind = obj["summary"]["kind"]
                require(
                    kind in ("trajectory", "surfaces", "markers", "polygons"),
                    "UNSUPPORTED_SCENE_OBJECT",
                    "Use trajectories or surface points",
                )
                require(
                    len(table) + point_count <= p["max_points"],
                    "VIEW_TOO_LARGE",
                    "Dataset exceeds scene point budget",
                )
                point_count += len(table)
                require(
                    {"x", "y", "z"} <= set(table),
                    "MISSING_TRAJECTORY",
                    "MD-only tops require an explicit trajectory during import",
                )
                for _, rows in table.groupby(
                    "well_id" if kind == "trajectory" else "polygon_id" if kind == "polygons" else "horizon"
                ):
                    rows = rows.sort_values("md") if kind == "trajectory" else rows
                    points = rows[["x", "y", "z"]].to_numpy(float)
                    if kind in ("trajectory", "polygons"):
                        require(len(points) >= 2, "INVALID_SCENE", "Well needs at least two survey points")
                        mesh = pv.lines_from_points(points)
                        plotter.add_mesh(
                            mesh,
                            color="#ffce70",
                            line_width=5,
                            opacity=item["opacity"],
                            name=key + str(len(plotter.actors)),
                        )
                    elif kind == "markers":
                        plotter.add_points(
                            points,
                            color="#ff856c",
                            point_size=12,
                            opacity=item["opacity"],
                            name=key + str(len(plotter.actors)),
                        )
                    else:
                        require(len(points) >= 3, "INVALID_SCENE", "Surface needs >=3 points")
                        mesh = pv.PolyData(points).delaunay_2d()
                        plotter.add_mesh(
                            mesh,
                            color="#59cbd0",
                            opacity=item["opacity"],
                            name=key + str(len(plotter.actors)),
                        )
                record["displayed_points"] = len(table)
            else:
                require(
                    False,
                    "UNSUPPORTED_SCENE_OBJECT",
                    "Supported: model/properties, trajectory/surfaces, seismic",
                )
            evidence.append(record)
        plotter.add_axes(xlabel="X (m)", ylabel="Y (m)", zlabel="Z up (m)", color="#e4eef2")
        plotter.set_scale(zscale=scales.pop())
        plotter.view_isometric()
        plotter.reset_camera()
        plotter.trame.export_html(out / "scene.html")
        plotter.screenshot(out / "scene.png")
    finally:
        plotter.close()
    summary = dict(
        backend="pyvista-trame-offline",
        displayed_cells=cell_count,
        displayed_points=point_count,
        actors=evidence,
        coordinate_unit="m",
        z_direction="up",
        scene=scene,
        scope="Interactive bounded preview; calculations always use complete immutable inputs",
    )
    (out / "scene.json").write_text(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    return "scene", summary, {name: out / name for name in ("scene.html", "scene.png", "scene.json")}
