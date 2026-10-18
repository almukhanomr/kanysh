"""Deck syntax found in the public Volve 2016 model: MAXVALUE/MINVALUE, unquoted edit records,
region edits, ADDZCORN, and the simulator's legacy .GRID geometry output."""

import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest

from opensubsurface.adapters.eclipse_binary import read_grid_file
from opensubsurface.adapters.eclipse_deck import Interpreter
from opensubsurface.adapters.local_sources import LocalSources, path_revision
from opensubsurface.errors import DomainError

GEOMETRY = (
    "COORD\n"
    + " ".join(
        " ".join(map(str, [i * 10, j * 10, 100, i * 10, j * 10, 120])) for j in range(2) for i in range(3)
    )
    + " /\nZCORN\n8*100 16*110 8*120 /\n"
)


def deck(service, tmp_path, grid_body):
    root = tmp_path / "src"
    root.mkdir(exist_ok=True)
    (root / "M.DATA").write_text(
        "RUNSPEC\nDIMENS\n2 1 2 /\nMETRIC\nGRID\n" + GEOMETRY + "ACTNUM\n4*1 /\nPORO\n4*0.2 /\n"
        "PERMX\n10 20 30 40 /\n" + grid_body + "EDIT\nMULTIREG\n PORV 0.91 2 F /\n/\nEND\n"
    )
    source = LocalSources(service.store).register("syntax", root)
    out = Path(tempfile.mkdtemp(dir=tmp_path))
    return Interpreter(source, "M.DATA", out, path_revision(root / "M.DATA")).parse()


def test_maxvalue_minvalue_and_unquoted_records_are_applied(service, tmp_path):
    parsed = deck(
        service,
        tmp_path,
        "MULTIPLY\n PERMX 2.0 1 2 1 1 1 2 /\n/\nMAXVALUE\n PERMX 50.0 1 2 1 1 1 2 /\n/\n"
        "MINVALUE\n 'PERMX' 30.0 1 1 1 1 1 1 /\n/\n",
    )
    # 10,20,30,40 -> x2 -> 20,40,60,80 -> max 50 -> 20,40,50,50 -> min 30 at (1,1,1) -> 30,40,50,50
    assert np.asarray(parsed.arrays["PERMX"]).tolist() == [30, 40, 50, 50]
    applied = [a["keyword"] for a in parsed.applied]
    assert applied[-3:] == ["MULTIPLY", "MAXVALUE", "MINVALUE"]
    region = [u for u in parsed.unsupported if u["keyword"] == "MULTIREG:PORV"]
    assert region and "not applied" in region[0]["reason"] and region[0]["line"] > 0


def test_addzcorn_is_refused_with_simulator_output_remediation(service, tmp_path):
    with pytest.raises(DomainError) as raised:
        deck(service, tmp_path, "ADDZCORN\n -10.0 0 1 1 0 1 2 0 1 1 0 /\n/\n")
    error = raised.value.as_dict()
    assert error["code"] == "UNSUPPORTED_GEOMETRY_EDIT" and "M.DATA" in error["message"]
    assert "EGRID" in error["remediation"]


def _array(stream, name, kind, values, width=8):
    stream.write(struct.pack(">i", 16) + name.ljust(8).encode() + struct.pack(">i", len(values)) + kind)
    stream.write(struct.pack(">i", 16))
    if kind == b"INTE":
        raw = np.asarray(values, ">i4").tobytes()
    elif kind == b"REAL":
        raw = np.asarray(values, ">f4").tobytes()
    else:
        raw = b"".join(v.ljust(width).encode() for v in values)
    stream.write(struct.pack(">i", len(raw)) + raw + struct.pack(">i", len(raw)))


def test_legacy_grid_file_corners_and_activity(service, tmp_path):
    root = tmp_path / "grid"
    root.mkdir()
    corners = {}
    with (root / "M.GRID").open("wb") as stream:
        _array(stream, "DIMENS", b"INTE", [2, 1, 1])
        _array(stream, "GRIDUNIT", b"CHAR", ["METRES", ""])
        _array(stream, "RADIAL", b"CHAR", ["FALSE"])
        for i in range(2):
            xyz = []
            for c in range(8):
                di, dj, dk = c % 2, (c // 2) % 2, c // 4
                # Second cell has a 3 m downthrow on its east pillar: a fault-like offset.
                z = 100 + 10 * dk + (3 if (i == 1 and di == 1) else 0)
                xyz += [10 * (i + di), 10 * dj, z]
            corners[i] = np.reshape(xyz, (8, 3))
            _array(stream, "COORDS", b"INTE", [i + 1, 1, 1, i + 1, int(i == 1), 0, 0])
            _array(stream, "CORNERS", b"REAL", xyz)
    source = LocalSources(service.store).register("grid", root)
    parsed = Interpreter(
        source, "M.GRID", Path(tempfile.mkdtemp(dir=tmp_path)), path_revision(root / "M.GRID")
    )
    read_grid_file(parsed, "M.GRID", path_revision(root / "M.GRID"))
    assert parsed.shape == (2, 1, 1) and parsed.unit == "METRIC"
    assert np.asarray(parsed.arrays["ACTNUM"]).tolist() == [0, 1]
    assert np.allclose(np.asarray(parsed.grid_corners), np.stack([corners[0], corners[1]]))
    assert parsed.grid_reconstruction["active_cells"] == 1
    parsed.grid_corners._mmap.close()


def test_parsing_strictness_is_explicit_and_documented():
    from opensubsurface.schemas import SimulationDeckRun
    from opensubsurface.simulation.runtime import command

    base = dict(
        project_id="p",
        source_id="s",
        path="A.DATA",
        file_revision="a" * 64,
        parameters_confirmed=True,
        assumptions=["x"],
    )
    assert SimulationDeckRun.model_validate(base).parsing_strictness == "normal"
    argv = command("linux", Path("/tmp/A.DATA"), "out", 2, "low")
    assert "--parsing-strictness=low" in argv and "--threads-per-process=2" in argv


def test_far_above_datum_goc_is_flagged_as_placeholder():
    from opensubsurface.adapters.folder_assess import inspect_text

    text = "EQUIL\n3060.0 337.0 3200.0 0.0 500.0 0.0 1 1 20 /\n2582.0 268.6 2692.0 0.0 2582.0 0.0 1 0 0 /\n"
    first, second = [p for p in inspect_text("E.prop", text.encode())[2] if p["parameter"] == "EQUIL"]
    assert "goc_z_m" not in first["regional_volumes_candidate"]
    assert "placeholder" in first["regional_volumes_candidate"]["note"]
    assert second["regional_volumes_candidate"]["goc_z_m"] == -2582.0
