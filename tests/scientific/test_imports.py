from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from opensubsurface.adapters.imports import import_dataset
from opensubsurface.errors import DomainError
from opensubsurface.schemas import DatasetImport


def test_las_nulls_depth_unit_and_real_fixture(tmp_path):
    source = Path("examples/templates/W-01.las")
    args = DatasetImport(
        project_id="p",
        upload_id="u",
        kind="las",
        well_id="W-01",
        units={"DEPT": "m"},
        crs="LOCAL_METRIC",
        vertical_datum="TEST",
    ).model_dump(mode="json")
    _, summary, files = import_dataset(source, args, tmp_path)
    table = pq.read_table(files["data.parquet"])
    assert summary["rows"] == 41
    assert np.isnan(table.column("PHI").to_numpy()[17])
    assert summary["null_fraction"]["PHI"] == pytest.approx(1 / 41)


def test_feet_conversion_invalid_md_and_normals(tmp_path):
    source = tmp_path / "collars.csv"
    source.write_text("well_id,x,y,reference_elevation\nA,100,200,10\n")
    args = DatasetImport(
        project_id="p",
        upload_id="u",
        kind="collars",
        crs="LOCAL_METRIC",
        vertical_datum="TEST",
        units=dict(x="ft", y="ft", reference_elevation="ft"),
    ).model_dump(mode="json")
    _, _, files = import_dataset(source, args, tmp_path)
    assert pq.read_table(files["data.parquet"]).to_pylist()[0]["x"] == pytest.approx(30.48)
    args.update(kind="trajectory", units=dict(md="m", x="m", y="m", z="m"))
    with pytest.raises(DomainError, match="возрастать"):
        import_dataset(Path("examples/templates/invalid_trajectory.csv"), args, tmp_path)
