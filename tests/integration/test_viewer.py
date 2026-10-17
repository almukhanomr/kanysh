import json
import os

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from opensubsurface.adapters.viewer import grid_geometry
from opensubsurface.errors import DomainError


def test_unified_pyvista_scene_persists_settings_and_publishes_real_html_png(service, tmp_path):
    pytest.importorskip("pyvista")
    pid = service.invoke("project_create", dict(name="Scene", vertical_datum="TEST"))["id"]
    grid = dict(shape=[3, 4, 2], extent=[0, 60, 0, 80, -1020, -1000])
    model = service.wait(
        service.invoke("model_build", dict(project_id=pid, grid=grid, horizontal_assumption=True))
    )
    refs = [dict(id=model["id"], revision=model["revision"])]
    for kind, data in [
        (
            "trajectory",
            dict(well_id=["W1"] * 3, md=[0, 20, 40], x=[10, 20, 30], y=[10, 30, 50], z=[-990, -1010, -1030]),
        ),
        (
            "surfaces",
            dict(horizon=["H1"] * 4, x=[0, 60, 0, 60], y=[0, 0, 80, 80], z=[-1005, -1005, -1006, -1006]),
        ),
        ("markers", dict(well_id=["W1"], horizon=["H1"], md=[20.0], x=[20.0], y=[30.0], z=[-1010.0])),
        (
            "polygons",
            dict(
                polygon_id=["boundary"] * 5,
                x=[0.0, 60.0, 60.0, 0.0, 0.0],
                y=[0.0, 0.0, 80.0, 80.0, 0.0],
                z=[-1005.0] * 5,
            ),
        ),
    ]:
        path = tmp_path / (kind + ".parquet")
        pq.write_table(pa.table(data), path)
        obj = service.store.publish(
            pid, "dataset", dict(kind=kind, rows=len(data["x"])), {"data.parquet": path}
        )
        refs.append(dict(id=obj["id"], revision=obj["revision"]))
    for r in refs:
        service.invoke("scene_show", dict(project_id=pid, ref=r, opacity=0.6, selected=True))
    volume = service.wait(service.invoke("seismic_generate", dict(project_id=pid, shape=[3, 4, 32])))
    vref = {k: volume[k] for k in ("id", "revision")}
    service.invoke("scene_show", dict(project_id=pid, ref=vref, velocity_m_s=2000, origin_z_m=-990))
    snapshot = service.invoke("scene_inspect", dict(project_id=pid))
    assert snapshot[model["id"]]["opacity"] == 0.6
    try:
        exported = service.wait(service.invoke("scene_export", dict(project_id=pid)))
    except DomainError as e:
        # Hosted CI runners (Windows) have no OpenGL; elsewhere a missing renderer is a failure.
        if e.code == "RENDERER_UNAVAILABLE" and os.environ.get("CI"):
            pytest.skip("No OpenGL context on this CI runner; scene rendering is NOT RUN here")
        raise
    assert exported["summary"]["displayed_cells"] == 24
    assert len(exported["summary"]["actors"]) == 6
    assert exported["summary"]["displayed_points"] == 3 + 4 + 1 + 5 + 4 * 32
    assert service.store.path(exported, "scene.png").read_bytes().startswith(b"\x89PNG")
    assert service.store.path(exported, "scene.html").stat().st_size > 100000
    saved = json.loads(service.store.path(exported, "scene.json").read_text())
    assert saved["scene"] == snapshot
    service.invoke("scene_show", dict(project_id=pid, ref=refs[0], stride=2, cell_range=[2, 10]))
    selected = service.invoke("scene_inspect", dict(project_id=pid))[model["id"]]
    obj = dict(model, paths={"arrays.npz": str(service.store.path(model, "arrays.npz"))})
    corners, _, ids = grid_geometry(obj, selected, 4)
    assert np.array_equal(ids, [2, 4, 6, 8])
    assert corners.shape == (4, 8, 3)
    with pytest.raises(DomainError, match="stride"):
        grid_geometry(obj, selected, 3)
