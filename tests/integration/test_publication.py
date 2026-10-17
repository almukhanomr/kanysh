"""Exercise the upload guard against real Git ignore/staging and nested archives."""

import importlib.util
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def audit(tmp_path, monkeypatch):
    # tmp_path may sit inside a checkout (e.g. --basetemp under the repo); Git must not
    # discover that parent repository, or the "uninitialized project" cases are not tested.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    spec = importlib.util.spec_from_file_location(
        "publication_guard", Path(__file__).parents[2] / "scripts/check_publication.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.inspect_project


def test_uninitialized_project_uses_ignore_rules_without_reading_owner_state(tmp_path, audit):
    (tmp_path / ".gitignore").write_text(".env\nstate/\n")
    token = "ghp_" + "A" * 36
    (tmp_path / ".env").write_text(token)
    (tmp_path / "state").mkdir()
    (tmp_path / "state/owner.json").write_text(token)
    (tmp_path / ".env.example").write_text("TOKEN=\n")
    result = audit(tmp_path)
    assert result["status"] == "PASS" and result["candidate_files"] == 2
    assert not (tmp_path / ".git").exists()


def test_tracked_ignored_secret_still_blocks_upload_without_echoing_value(tmp_path, audit):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".env\n")
    token = "ghp_" + "B" * 36
    (tmp_path / ".env").write_text("TOKEN=" + token)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", ".env"], check=True)
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert {f["kind"] for f in result["findings"]} >= {"github_token", "local_configuration"}
    assert token not in json.dumps(result)


def test_nested_archive_and_symlink_cannot_bypass_upload_guard(tmp_path, audit):
    token = "ghp_" + "C" * 36
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("credential.txt", token)
    with zipfile.ZipFile(tmp_path / "example.zip", "w") as archive:
        archive.writestr("nested.zip", inner.getvalue())
    (tmp_path / "link.txt").symlink_to(tmp_path.parent / "not-an-audit-input")
    result = audit(tmp_path)
    assert result["status"] == "FAIL"
    assert {f["kind"] for f in result["findings"]} >= {"github_token", "symlink"}
    assert any("!nested.zip!credential.txt" in f["path"] for f in result["findings"])
    assert token not in json.dumps(result)
