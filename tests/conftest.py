import io

import numpy as np
import pytest

from opensubsurface.service import Service


@pytest.fixture
def service(tmp_path):
    s = Service(tmp_path / "data")
    yield s
    s.close()


@pytest.fixture
def demo(service):
    return service.demo()


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Keep generated public JUnit evidence portable, including skipped-test messages."""
    import subprocess
    import sys
    from pathlib import Path

    path = session.config.option.xmlpath
    if path and Path(path).exists():
        script = Path(__file__).resolve().parents[1] / "scripts/publication.py"
        subprocess.run([sys.executable, str(script), "--junit", str(path)], check=True)


def _demo_wells(service, project_id):
    project = service.store.project(project_id)
    base = dict(project_id=project_id, crs=project["crs"], vertical_datum=project["vertical_datum"])
    results = []
    csvs = {
        "collars": "well_id,x,y,reference_elevation\nW-01,250,250,0\nW-02,750,750,0\n",
        "trajectory": "well_id,md,x,y,z\nW-01,0,250,250,0\nW-01,1050,250,250,-1050\nW-02,0,750,750,0\nW-02,1050,750,750,-1050\n",
        "markers": "well_id,horizon,md\nW-01,Top,1000\nW-01,Base,1020\nW-02,Top,1000\nW-02,Base,1020\n",
    }
    for kind, text in csvs.items():
        upload = service.store.upload(project_id, kind + ".csv", io.BytesIO(text.encode()))
        units = {k: "m" for k in ("x", "y", "z", "md", "reference_elevation")}
        obj = service.wait(
            service.invoke("dataset_import", dict(base, upload_id=upload["id"], kind=kind, units=units))
        )
        results.append(obj["id"])
    for well, offset in [("W-01", 0), ("W-02", 0.02)]:
        lines = [
            "~Version",
            " VERS. 2.0 : VERSION",
            " WRAP. NO : WRAP",
            "~Well",
            " STRT.M 990 : START",
            " STOP.M 1030 : STOP",
            " STEP.M 1 : STEP",
            " NULL. -999.25 : NULL",
            f" WELL. {well} : WELL",
            "~Curve",
            " DEPT.M : MD",
            " PHI.V/V : POROSITY",
            " GR.API : GAMMA",
            "~A",
        ]
        for md in range(990, 1031):
            phi = -999.25 if md == 1007 else 0.2 + offset + 0.015 * np.sin(md * 0.4)
            lines.append(f"{md} {phi:.8f} {60 + 20 * np.cos(md * 0.2):.5f}")
        upload = service.store.upload(
            project_id, well + ".las", io.BytesIO(("\n".join(lines) + "\n").encode())
        )
        obj = service.wait(
            service.invoke(
                "dataset_import",
                dict(base, upload_id=upload["id"], kind="las", units={"DEPT": "m"}, well_id=well),
            )
        )
        results.append(obj["id"])
    return dict(created=results, provenance="Synthetic Apache-2.0; curves are not measured field data")


@pytest.fixture
def demo_wells():
    return _demo_wells


@pytest.fixture(autouse=True)
def windows_symlink_privilege(monkeypatch):
    """Only symlink creation tests skip on Windows lacking Developer Mode privilege.

    Native junction, source identity, cancellation and lock tests still execute.
    """
    import os
    from pathlib import Path

    if os.name != "nt":
        return
    original = Path.symlink_to

    def symlink(path, *args, **kwargs):
        try:
            return original(path, *args, **kwargs)
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                pytest.skip(
                    "Windows symlink creation requires Developer Mode or SeCreateSymbolicLinkPrivilege"
                )
            raise

    monkeypatch.setattr(Path, "symlink_to", symlink)
