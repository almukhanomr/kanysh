import numpy as np

from opensubsurface.domain.numerics import grid_arrays
from opensubsurface.errors import require


def gempy_build(p, surfaces, orientations, device, fault=None):
    import gempy as gp
    from gempy_engine.config import AvailableBackends

    require(len(surfaces) >= 3, "QC_FAILED", "GemPy требует минимум три surface points")
    encountered = list(dict.fromkeys(surfaces.horizon.astype(str)))
    order = p.get("stratigraphic_order") or encountered
    require(
        len(encountered) == 1 or bool(p.get("stratigraphic_order")),
        "QC_FAILED",
        "Для нескольких горизонтов задайте stratigraphic_order от молодого к старому",
    )
    require(
        set(order) == set(encountered) and len(order) == len(encountered),
        "QC_FAILED",
        "stratigraphic_order должен содержать все горизонты ровно один раз",
    )
    surfaces = surfaces.assign(_rank=surfaces.horizon.map({h: i for i, h in enumerate(order)})).sort_values(
        "_rank"
    )
    names = surfaces.horizon.astype(str).to_numpy()
    points = gp.data.SurfacePointsTable.from_arrays(
        x=surfaces.x.to_numpy(), y=surfaces.y.to_numpy(), z=surfaces.z.to_numpy(), names=names
    )
    if orientations is None:
        require(
            p["horizontal_assumption"],
            "MISSING_ORIENTATIONS",
            "Нужны orientations или явно выбранные горизонтальные слои",
        )
        selected = surfaces.groupby("horizon", sort=False).first().reset_index()
        x, y, z = selected.x.to_numpy(), selected.y.to_numpy(), selected.z.to_numpy()
        ox, oy, oz = np.zeros(len(x)), np.zeros(len(x)), np.ones(len(x))
        onames = selected.horizon.astype(str).to_numpy()
    else:
        x, y, z = (orientations[k].to_numpy() for k in ("x", "y", "z"))
        ox, oy, oz = (orientations[k].to_numpy() for k in ("nx", "ny", "nz"))
        onames = orientations.horizon.astype(str).to_numpy()
    orient = gp.data.OrientationsTable.from_arrays(
        x=x, y=y, z=z, G_x=ox, G_y=oy, G_z=oz, names=onames, name_id_map=points.name_id_map
    )
    frame = gp.data.StructuralFrame.from_data_tables(points, orient)
    frame.structural_groups[0].elements.sort(key=lambda element: order.index(element.name))
    if fault is not None:
        fp = np.asarray(fault["points"], float)
        normal = np.asarray(fault["normal"], float)
        name = fault["name"]
        require(name not in encountered, "QC_FAILED", "Имя разлома совпадает с горизонтом")
        element = gp.data.StructuralElement(
            name=name,
            color=next(frame.color_generator),
            surface_points=gp.data.SurfacePointsTable.from_arrays(
                x=fp[:, 0], y=fp[:, 1], z=fp[:, 2], names=name
            ),
            orientations=gp.data.OrientationsTable.from_arrays(
                x=fp[:1, 0],
                y=fp[:1, 1],
                z=fp[:1, 2],
                G_x=normal[:1],
                G_y=normal[1:2],
                G_z=normal[2:3],
                names=name,
            ),
        )
        frame.insert_group(
            0,
            gp.data.StructuralGroup(
                name="Fault",
                elements=[element],
                structural_relation=gp.data.StackRelationType.FAULT,
                fault_relations=gp.data.FaultsRelationSpecialCase.OFFSET_ALL,
            ),
        )
        gp.set_fault_relation(frame, np.array([[False, True], [False, False]]))
    model = gp.create_geomodel(
        project_name="Kanysh Basic",
        extent=p["grid"]["extent"],
        resolution=p["grid"]["shape"],
        refinement=1,
        structural_frame=frame,
    )
    centers, _ = grid_arrays(p["grid"])
    gp.set_custom_grid(model.grid, centers.reshape(-1, 3), reset=True)
    # Evaluate custom grid only; world coordinates normalized internally by GemPy.
    solution = gp.compute_model(
        model,
        engine_config=gp.data.GemPyEngineConfig(
            backend=AvailableBackends.PYTORCH, use_gpu=(device == "cuda"), dtype=p["execution"]["precision"]
        ),
    )
    values = np.asarray(solution.raw_arrays.custom)
    if values.ndim == 2:
        values = values[0]
    zones = np.rint(values).astype(int).reshape(p["grid"]["shape"])
    require((zones > 0).all(), "QC_FAILED", "GemPy вернул неизвестные lithology IDs")
    transform = model.input_transform
    return zones, dict(
        gempy_version=gp.__version__,
        coordinate_transform=dict(
            position=np.asarray(transform.position).tolist(),
            scale=np.asarray(transform.scale).tolist(),
            rotation=np.asarray(transform.rotation).tolist(),
        ),
        stratigraphic_order=list(dict.fromkeys(names.tolist())),
        fault_geometry=fault,
    )
