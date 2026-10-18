"""Native filesystem checks execute on Windows CI, never simulated with POSIX paths."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from opensubsurface.adapters.local_sources import LocalSources, parts, path_revision, revision
from opensubsurface.desktop import configured_home
from opensubsurface.errors import DomainError
from opensubsurface.platform_io import _extended, read_at


@pytest.mark.parametrize("path", ["C:/outside.csv", "C:outside.csv", "file.csv:secret", "dir./x", "dir /x"])
def test_windows_aliases_cannot_escape_relative_source_path(path):
    with pytest.raises(DomainError):
        parts(path)


def test_read_at_without_posix_pread(tmp_path, monkeypatch):
    path = tmp_path / "binary"
    path.write_bytes(bytes(range(255)) * 10)
    monkeypatch.delattr(os, "pread", raising=False)
    with path.open("rb") as stream:
        assert read_at(stream.fileno(), 8, 253) == path.read_bytes()[253:261]
        assert read_at(stream.fileno(), 4, 3) == bytes(range(3, 7))


def test_installer_home_expands_environment_without_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("KANYSH_TEST_HOME", str(tmp_path))
    # expandvars follows the host syntax; no shell invocation is involved.
    value = "%KANYSH_TEST_HOME%" if sys.platform == "win32" else "$KANYSH_TEST_HOME"
    assert configured_home(value) == tmp_path


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows NTFS handles and case semantics")
def test_windows_drive_case_long_unicode_paths_and_identity(service, tmp_path):
    root = tmp_path / "Геология FieldA"
    root.mkdir()
    file = root / "PORO.INC"
    file.write_bytes(b"PORO\n1*0.2 /\n")
    sources = LocalSources(service.store)
    source = sources.register("NTFS", root)
    assert sources.register("same root different case", str(root).swapcase())["id"] == source["id"]
    assert Path(source["root"]).is_absolute() and source["inode"] != 0
    with sources.opened(source["id"], "poro.inc") as (fd, _):
        assert revision(os.fstat(fd)) == path_revision(file)
        assert os.read(fd, 100) == file.read_bytes()
    relative = "/".join(["long-directory-" + str(i) + "a" * 30 for i in range(8)])
    # Fixture creation must work even when Windows LongPathsEnabled is off.
    # The production reader below still receives the ordinary registered path.
    deep = Path(_extended(root / relative))
    deep.mkdir(parents=True)
    (deep / "data.inc").write_bytes(b"NTG\n1 /\n")
    with sources.opened(source["id"], relative + "/data.inc") as (fd, _):
        assert os.read(fd, 100) == b"NTG\n1 /\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows junctions and deny-delete handle sharing")
def test_windows_junction_cannot_expand_access_and_open_root_cannot_be_swapped(service, tmp_path):
    root, outside = tmp_path / "model", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.inc").write_bytes(b"must not read")
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(root / "link"), str(outside)],
        check=True,
        capture_output=True,
    )
    sources = LocalSources(service.store)
    source = sources.register("NTFS", root)
    try:
        with pytest.raises(DomainError):
            sources.register("Forbidden", root / "link")
        with pytest.raises(DomainError):
            with sources.opened(source["id"], "link/secret.inc"):
                pytest.fail("junction followed")
        listing = sources.scan(
            dict(source_id=source["id"], path="", offset=0, limit=10, listing_revision=None)
        )
        assert listing["entries"] == []
        with sources.opened(source["id"], "", directory=True):
            with pytest.raises(OSError):
                root.rename(tmp_path / "replaced")
    finally:
        (root / "link").rmdir()


def test_control_plane_lock_excludes_an_independent_process(service):
    import portalocker

    service.file_lock = (service.store.root / "control-plane.lock").open("a+")
    portalocker.lock(service.file_lock, portalocker.LOCK_EX | portalocker.LOCK_NB)
    script = """
import sys,portalocker
with open(sys.argv[1], 'a+') as stream:
    try:
        portalocker.lock(stream, portalocker.LOCK_EX | portalocker.LOCK_NB)
    except portalocker.exceptions.LockException:
        print('EXCLUDED')
    else:
        print('LOCKED')
"""
    args = [sys.executable, "-c", script, str(service.store.root / "control-plane.lock")]
    assert subprocess.check_output(args, text=True).strip() == "EXCLUDED"
    service.close()
    assert subprocess.check_output(args, text=True).strip() == "LOCKED"


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_simulation_requires_linux_before_any_solver_or_reader(tmp_path, monkeypatch, platform):
    from opensubsurface.adapters import opm

    monkeypatch.setattr(opm.sys, "platform", platform)
    with pytest.raises(DomainError) as error:
        opm.run_case({}, {}, tmp_path)
    assert error.value.code == "SOLVER_PLATFORM_UNSUPPORTED" and "Linux/WSL" in error.value.message
    assert not list(tmp_path.iterdir())


def test_bundle_cpu_index_and_windows_owner_configuration(tmp_path):
    import importlib.util
    import tomllib
    import zipfile

    spec = importlib.util.spec_from_file_location(
        "builder", Path(__file__).parents[2] / "scripts/build_mcpb.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    path = tmp_path / "test.mcpb"
    builder.build(path)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        project = tomllib.loads(archive.read("pyproject.toml").decode())
        assert "win32" in manifest["compatibility"]["platforms"]
        assert manifest["user_config"]["home"]["default"] == r"%LOCALAPPDATA%\kanysh-basic"
        assert manifest["user_config"]["data_folder"]["type"] == "directory"
        assert project["tool"]["uv"]["sources"]["torch"]["index"] == "pytorch-cpu"
        assert not any("resdata" in requirement for requirement in project["project"]["dependencies"])
