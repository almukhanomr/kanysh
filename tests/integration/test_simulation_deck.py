"""OPM Flow deck runs: portable summary reader, deck closure, optional simulator, cancellation.

The Norne acceptance test runs only where OPM Flow is set up (`kanysh-basic setup-opm`) and the
deck plus the ECLIPSE 2014.2 reference summary are available (KANYSH_NORNE_DIR, KANYSH_NORNE_ECL_DIR).
"""

import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from opensubsurface.adapters.local_sources import LocalSources, path_revision
from opensubsurface.errors import DomainError
from opensubsurface.simulation import deck, runtime, summary


def _array(stream, endian, name, kind, values, size=None):
    count = len(values)
    stream.write(struct.pack(endian + "i", 16))
    stream.write(name.ljust(8).encode() + struct.pack(endian + "i", count) + kind)
    stream.write(struct.pack(endian + "i", 16))
    if kind in (b"INTE", b"REAL"):
        raw = np.asarray(values, dtype=endian + ("i4" if kind == b"INTE" else "f4")).tobytes()
    else:
        width = size or 8
        raw = b"".join(v.ljust(width).encode() for v in values)
    if raw:
        stream.write(struct.pack(endian + "i", len(raw)) + raw + struct.pack(endian + "i", len(raw)))


def write_summary(folder, stem, rows, endian=">", long_names=False):
    keys = ["TIME", "FOPT", "WOPR", "BPR"]
    names = [":+:+:+:+", "FIELD", "B-2H-LONG-WELL" if long_names else "B-2H", ":+:+:+:+"]
    with (folder / f"{stem}.SMSPEC").open("wb") as stream:
        _array(stream, endian, "DIMENS", b"INTE", [len(keys), 1, 1, 1, 0, -1])
        _array(stream, endian, "KEYWORDS", b"CHAR", keys)
        if long_names:
            _array(stream, endian, "NAMES", b"C016", names[:4], 16)
        else:
            _array(stream, endian, "WGNAMES", b"CHAR", names[:4])
        _array(stream, endian, "NUMS", b"INTE", [0, 0, 0, 42])
        _array(stream, endian, "UNITS", b"CHAR", ["DAYS", "SM3", "SM3/DAY", "BARSA"])
        _array(stream, endian, "STARTDAT", b"INTE", [6, 11, 1997])
    with (folder / f"{stem}.UNSMRY").open("wb") as stream:
        for step, row in enumerate(rows):
            _array(stream, endian, "SEQHDR", b"INTE", [step])
            _array(stream, endian, "MINISTEP", b"INTE", [step])
            _array(stream, endian, "PARAMS", b"REAL", row)
    return folder / f"{stem}.SMSPEC"


@pytest.mark.parametrize("endian,long_names", [(">", False), ("<", True)])
def test_portable_summary_reader_and_explicit_comparison(tmp_path, endian, long_names):
    rows = [[0, 0, 0, 270], [10, 100, 10, 268], [20, 220, 12, 266]]
    data = summary.read(write_summary(tmp_path, "A", rows, endian, long_names))
    well = "WOPR:B-2H-LONG-WELL" if long_names else "WOPR:B-2H"
    assert data["start"] == "1997-11-06T00:00:00+00:00" and data["keys"] == ["TIME", "FOPT", well, "BPR:42"]
    assert summary.vector(data, "FOPT").tolist() == [0, 100, 220] and data["units"][1] == "SM3"
    other = tmp_path / "ref"
    other.mkdir()
    reference = summary.read(
        write_summary(other, "R", [[0, 0, 0, 270], [20, 200, 10, 266]], endian, long_names)
    )
    result = summary.compare(data, reference, ["FOPT", "FWPT"], 0.05)
    fopt, missing = result["vectors"]
    # Reference interpolated at day 10 is 100; at day 20 the result is 10% above 200.
    assert fopt["max_normalized_deviation"] == pytest.approx(0.1) and fopt["status"] == "DIFFERENCE"
    assert fopt["final_relative_difference"] == pytest.approx(0.1)
    assert missing["status"] == "NOT RUN"
    with pytest.raises(DomainError):
        summary.vector(data, "FGPT")


def test_formatted_or_truncated_summary_is_rejected(tmp_path):
    (tmp_path / "F.SMSPEC").write_text(" 'DIMENS  '           6 'INTE'\n")
    with pytest.raises(DomainError, match="unformatted"):
        summary.read(tmp_path / "F.SMSPEC")
    path = write_summary(tmp_path, "T", [[0, 0, 0, 1]])
    path.with_suffix(".UNSMRY").write_bytes(path.with_suffix(".UNSMRY").read_bytes()[:-6])
    with pytest.raises(DomainError):
        summary.read(path)


def _source(service, tmp_path, main, files):
    folder = tmp_path / "deck"
    for name, text in {**files, "MAIN.DATA": main}.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    source = LocalSources(service.store).register("deck", folder)
    listing = {f["path"]: f for f in service.invoke("folder_assess", dict(source_id=source["id"]))["files"]}
    return source, listing


def test_deck_closure_follows_includes_and_refuses_external_files(service, tmp_path):
    main = "RUNSPEC\nGRID\nINCLUDE\n 'INCLUDE/GRID/g.inc' /\nSCHEDULE\nINCLUDE\n'sched.sch' /\n-- INCLUDE\n-- 'x.inc' /\n"
    files = {
        "INCLUDE/GRID/g.inc": "PORO\n1*0.2 /\nINCLUDE\n'INCLUDE/PETRO/p.inc' /\n",
        "INCLUDE/PETRO/p.inc": "NTG\n1 /\n",
    }
    files["sched.sch"] = "TSTEP\n1 /\n"
    source, listing = _source(service, tmp_path, main, files)
    closure = deck.closure(source, "MAIN.DATA", listing["MAIN.DATA"]["file_revision"])
    # Nested INCLUDE paths resolve relative to the main DATA file (ECLIPSE/OPM convention).
    assert [f["path"] for f in closure] == [
        "MAIN.DATA",
        "INCLUDE/GRID/g.inc",
        "sched.sch",
        "INCLUDE/PETRO/p.inc",
    ]
    target = tmp_path / "copy"
    hashes = deck.snapshot(source, closure, target)
    assert (target / "INCLUDE/PETRO/p.inc").read_text() == "NTG\n1 /\n" and len(hashes) == 4
    for bad, code in [
        ("SOLUTION\nRESTART\n'BASE' 10 /\n", "UNSUPPORTED_DECK"),
        ("INCLUDE\n'../x.inc' /\n", None),
    ]:
        (tmp_path / "deck/MAIN.DATA").write_text(bad)
        revision = service.invoke("folder_assess", dict(source_id=source["id"]))["files"]
        revision = {f["path"]: f for f in revision}["MAIN.DATA"]["file_revision"]
        with pytest.raises(DomainError) as raised:
            deck.closure(source, "MAIN.DATA", revision)
        assert code is None or raised.value.code == code


def test_deck_run_is_refused_synchronously_without_simulator(service, tmp_path, monkeypatch):
    monkeypatch.setattr(
        runtime,
        "status",
        lambda home: dict(available=False, reason="WSL2 is not installed", remediation="wsl --install"),
    )
    pid = service.invoke("project_create", dict(name="sim", vertical_datum="T"))["id"]
    with pytest.raises(DomainError) as raised:
        service.invoke(
            "simulation_deck_run",
            dict(
                project_id=pid,
                source_id="s",
                path="A.DATA",
                file_revision="a" * 64,
                parameters_confirmed=True,
                assumptions=["x"],
            ),
        )
    error = raised.value.as_dict()
    assert error["code"] == "SIMULATOR_UNAVAILABLE" and "wsl --install" in error["remediation"]
    assert service.store.list_jobs(pid) == []
    assert service.invoke("diagnostics", dict(lines=5))["simulator"]["available"] is False


def test_cancel_stops_simulator_outside_the_windows_process_tree(tmp_path, monkeypatch):
    from opensubsurface.execution import runner

    calls = []
    monkeypatch.setattr("opensubsurface.simulation.runtime.kill_external", lambda d: calls.append(Path(d)))
    (tmp_path / "flow-process.json").write_text(json.dumps(dict(pid=1, executor="wsl")))
    runner.stop_external(tmp_path)
    assert calls == [tmp_path]
    runner.stop_external(tmp_path / "missing")
    assert len(calls) == 1


NORNE = os.environ.get("KANYSH_NORNE_DIR")
ECL = os.environ.get("KANYSH_NORNE_ECL_DIR")


@pytest.mark.opm
@pytest.mark.skipif(not (NORNE and ECL), reason="Set KANYSH_NORNE_DIR and KANYSH_NORNE_ECL_DIR")
def test_norne_flow_against_eclipse_reference(service, tmp_path):
    """Acceptance: unmodified Norne deck in pinned OPM Flow vs ECLIPSE 2014.2 (opm-tests).

    The 5 % criterion on field cumulative volumes is fixed here before running; metrics are
    recorded as computed and the report keeps every vector's status.
    """
    import shutil

    if not runtime.status(service.store.root)["available"]:
        pinned = Path(os.environ.get("KANYSH_OPM_HOME", ".data/opm-home")) / runtime.RUNTIME_FILE
        if not pinned.is_file():
            pytest.skip("Run `kanysh-basic setup-opm` first")
        shutil.copyfile(pinned, service.store.root / runtime.RUNTIME_FILE)
    folder = tmp_path / "norne"
    shutil.copytree(NORNE, folder)
    for name in ("NORNE_ATW2013.SMSPEC", "NORNE_ATW2013.UNSMRY"):
        (folder / "ECL.2014.2").mkdir(exist_ok=True)
        shutil.copyfile(Path(ECL) / name, folder / "ECL.2014.2" / name)
    source = LocalSources(service.store).register("Norne", folder)
    listing = {
        f["path"]: f
        for f in service.invoke("folder_assess", dict(source_id=source["id"], max_depth=4, max_files=500))[
            "files"
        ]
    }
    revision = {
        name: path_revision(folder / name)
        for name in ("ECL.2014.2/NORNE_ATW2013.SMSPEC", "ECL.2014.2/NORNE_ATW2013.UNSMRY")
    }
    pid = service.invoke("project_create", dict(name="Norne OPM", crs="EPSG:23032", vertical_datum="MSL"))[
        "id"
    ]
    vectors = ["FOPT", "FWPT", "FGPT", "FWIT", "FGIT"]
    result = service.wait(
        service.invoke(
            "simulation_deck_run",
            dict(
                project_id=pid,
                source_id=source["id"],
                path="NORNE_ATW2013.DATA",
                file_revision=listing["NORNE_ATW2013.DATA"]["file_revision"],
                threads=min(4, os.cpu_count() or 1),
                reference=dict(
                    smspec_path="ECL.2014.2/NORNE_ATW2013.SMSPEC",
                    smspec_revision=revision["ECL.2014.2/NORNE_ATW2013.SMSPEC"],
                    data_path="ECL.2014.2/NORNE_ATW2013.UNSMRY",
                    data_revision=revision["ECL.2014.2/NORNE_ATW2013.UNSMRY"],
                    vectors=vectors,
                    relative_tolerance=0.05,
                ),
                execution=dict(timeout_seconds=14400),
                parameters_confirmed=True,
                assumptions=["Unmodified public Norne deck; ECLIPSE 2014.2 reference from OPM/opm-tests"],
            ),
        ),
        timeout=14400,
    )
    report = json.loads(service.store.path(result, "report.json").read_text(encoding="utf-8"))
    print("\nNorne OPM vs ECLIPSE:", json.dumps(report["comparison"]["vectors"], indent=1))
    assert report["final_day"] == pytest.approx(3312, abs=1)
    assert {row["vector"]: row["status"] for row in report["comparison"]["vectors"]} == dict.fromkeys(
        vectors, "PASS"
    )
    assert report["validation_status"] == "PASS" and "SMSPEC" in " ".join(result["files"])
