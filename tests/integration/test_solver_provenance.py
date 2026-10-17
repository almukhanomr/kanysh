import builtins
import sys

import pytest

from opensubsurface.adapters.opm import run_case
from opensubsurface.errors import DomainError
from opensubsurface.execution import provenance


def test_cache_invalidates_on_reader_and_solver_changes(tmp_path, monkeypatch):
    executable = tmp_path / "flow-test-identity-only"
    executable.write_bytes(b"fixture binary v1; never executed")
    executable.chmod(0o700)
    monkeypatch.setenv("OPENSUBSURFACE_FLOW_EXECUTABLE", str(executable))
    original = provenance.importlib.metadata.version
    reader = ["fixture-reader-v1"]
    monkeypatch.setattr(
        provenance.importlib.metadata,
        "version",
        lambda name: reader[0] if name == "resdata" else original(name),
    )
    first = provenance.fingerprint()
    reader[0] = "fixture-reader-v2"
    second = provenance.fingerprint()
    assert first != second and first["flow"] == second["flow"]
    executable.write_bytes(b"fixture binary v2; never executed")
    third = provenance.fingerprint()
    assert second["flow"]["sha256"] != third["flow"]["sha256"]
    assert second["source_hash"] == third["source_hash"]


@pytest.mark.parametrize("missing", ["standard_conditions", "reader"])
def test_invalid_case_or_missing_reader_rejected_before_solver(tmp_path, monkeypatch, missing):
    monkeypatch.setenv("OPENSUBSURFACE_FLOW_EXECUTABLE", sys.executable)
    original_import = builtins.__import__
    if missing == "reader":

        def without_resdata(name, *args, **kwargs):
            if name.startswith("resdata"):
                raise ImportError("Deliberately unavailable optional dependency")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", without_resdata)
    context = (
        {}
        if missing == "standard_conditions"
        else dict(standard_conditions=dict(pressure_pa=101325, temperature_k=288.71))
    )
    params = dict(execution=dict(device_policy="cpu_only"), _case_summary=context)
    files = {name: tmp_path / name for name in ("CASE.DATA", "mapping.npz", "initial_state.npz")}
    with pytest.raises(DomainError) as error:
        run_case(files, params, tmp_path)
    assert error.value.code == (
        "INPUT_REVISION_CONFLICT" if missing == "standard_conditions" else "RESULT_READER_UNAVAILABLE"
    )
    assert not (tmp_path / "solver").exists()
