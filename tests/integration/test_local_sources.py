import io
import os

import pytest

from opensubsurface.adapters.local_sources import LocalSources, revision
from opensubsurface.errors import DomainError


def setup_source(service, tmp_path):
    directory = tmp_path / "geology"
    directory.mkdir()
    (directory / "collars.csv").write_text("well_id,x,y,reference_elevation\nW1,0,0,0\n")
    source = LocalSources(service.store).register("Geology", directory)
    return directory, source


def scan(service, source, **args):
    return service.invoke("source_scan", dict(source_id=source["id"], **args))


def test_source_snapshot_enters_actual_import_pipeline(service, tmp_path):
    directory, source = setup_source(service, tmp_path)
    assert LocalSources(service.store).register("Same folder", directory)["id"] == source["id"]
    assert service.invoke("source_list", {})[0]["read_only"]
    entry = scan(service, source)["entries"][0]
    pid = service.invoke("project_create", dict(name="Local", vertical_datum="TEST"))["id"]
    uploaded = service.invoke(
        "source_upload",
        dict(
            project_id=pid, source_id=source["id"], **{key: entry[key] for key in ("path", "file_revision")}
        ),
    )
    assert uploaded["source"]["source_id"] == source["id"]
    assert (
        service.store.upload_path(pid, uploaded["id"]).read_bytes()
        == (directory / "collars.csv").read_bytes()
    )
    result = service.wait(
        service.invoke(
            "dataset_import",
            dict(
                project_id=pid,
                upload_id=uploaded["id"],
                kind="collars",
                units={"x": "m", "y": "m", "reference_elevation": "m"},
                crs="LOCAL_METRIC",
                vertical_datum="TEST",
            ),
        )
    )
    assert result["kind"] == "dataset" and result["summary"]["rows"] == 1
    assert result["parameters"]["input_file"]["source"]["file_revision"] == entry["file_revision"]
    assert result["parameters"]["input_file"]["content_hash"] == uploaded["content_hash"]
    LocalSources(service.store).remove(source["id"])
    assert service.invoke("source_list", {}) == []
    # Revoking source access does not remove already pinned project input snapshots.
    assert service.store.upload_path(pid, uploaded["id"]).is_file()


def test_listing_is_metadata_only_paginated_and_changed_files_rejected(service, tmp_path):
    directory, source = setup_source(service, tmp_path)
    (directory / "second.las").write_text("Fixture")
    (directory / ".private.csv").write_text("Hidden")
    (directory / "unsupported.key").write_text("Excluded")
    page = scan(service, source, limit=1)
    assert page["total"] == 2 and not page["content_read"] and page["next_offset"] == 1
    second = scan(service, source, offset=1, limit=1, listing_revision=page["listing_revision"])
    assert second["next_offset"] is None and second["entries"][0]["path"] == "second.las"
    with pytest.raises(DomainError, match="listing_revision"):
        scan(service, source, offset=1)
    old = page["entries"][0]
    (directory / "collars.csv").write_text("Changed fixture")
    with pytest.raises(DomainError, match="changed"):
        scan(service, source, offset=1, listing_revision=page["listing_revision"])
    pid = service.invoke("project_create", dict(name="Changed", vertical_datum="TEST"))["id"]
    with pytest.raises(DomainError, match="changed"):
        service.invoke(
            "source_upload",
            dict(
                project_id=pid, source_id=source["id"], path=old["path"], file_revision=old["file_revision"]
            ),
        )


@pytest.mark.parametrize(
    "path", ["../outside.csv", "/etc/passwd", ".private.csv", "folder/../../escape", "a\\b.csv"]
)
def test_relative_source_path_cannot_escape(service, tmp_path, path):
    _, source = setup_source(service, tmp_path)
    with pytest.raises(DomainError) as error:
        scan(service, source, path=path)
    assert error.value.code == "INVALID_SOURCE_PATH"


def test_symlink_and_replaced_root_cannot_expand_access(service, tmp_path):
    directory, source = setup_source(service, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.csv").write_text("Must not read")
    (directory / "link").symlink_to(outside, target_is_directory=True)
    (directory / "linked.csv").symlink_to(outside / "secret.csv")
    assert [e["path"] for e in scan(service, source)["entries"]] == ["collars.csv"]
    with pytest.raises(DomainError):
        scan(service, source, path="link")
    pid = service.invoke("project_create", dict(name="Symlink", vertical_datum="TEST"))["id"]
    with pytest.raises(DomainError):
        service.invoke(
            "source_upload",
            dict(project_id=pid, source_id=source["id"], path="linked.csv", file_revision="a" * 64),
        )
    directory.rename(tmp_path / "old-geology")
    directory.mkdir()
    (directory / "new.csv").write_text("Requires owner registration")
    with pytest.raises(DomainError) as error:
        scan(service, source)
    assert error.value.code == "SOURCE_CHANGED"


@pytest.mark.parametrize("action", ["modify", "revoke"])
def test_change_or_revocation_during_copy_never_publishes_upload(service, tmp_path, monkeypatch, action):
    directory, source = setup_source(service, tmp_path)
    entry = scan(service, source)["entries"][0]
    pid = service.invoke("project_create", dict(name="Race", vertical_datum="TEST"))["id"]
    original = service.store.upload

    def changing_upload(project_id, name, stream, **kwargs):
        class ChangingStream(io.RawIOBase):
            def read(self, size):
                chunk = stream.read(size)
                if chunk:
                    if action == "modify":
                        (directory / "collars.csv").write_text("Modified during copy")
                    else:
                        LocalSources(service.store).remove(source["id"])
                return chunk

        return original(project_id, name, ChangingStream(), **kwargs)

    monkeypatch.setattr(service.store, "upload", changing_upload)
    with pytest.raises(DomainError):
        service.invoke(
            "source_upload",
            dict(
                project_id=pid,
                source_id=source["id"],
                path=entry["path"],
                file_revision=entry["file_revision"],
            ),
        )
    assert list((service.store.root / "uploads").iterdir()) == []


def test_large_file_can_be_listed_without_claiming_large_model_compute(service, tmp_path):
    directory, source = setup_source(service, tmp_path)
    with (directory / "large.segy").open("wb") as stream:
        stream.truncate(257 * 1024**2)  # Sparse metadata fixture, not a real seismic cube.
    entry = next(e for e in scan(service, source)["entries"] if e["path"] == "large.segy")
    assert entry["size_bytes"] == 257 * 1024**2
    pid = service.invoke("project_create", dict(name="Bounded", vertical_datum="TEST"))["id"]
    with pytest.raises(DomainError) as error:
        service.invoke(
            "source_upload",
            dict(
                project_id=pid,
                source_id=source["id"],
                path=entry["path"],
                file_revision=entry["file_revision"],
            ),
        )
    assert error.value.code == "UPLOAD_TOO_LARGE"


@pytest.mark.parametrize("relative", ["collars.csv", "nested/Геология.INC"])
def test_scan_revision_matches_open_file_and_mutation_still_rejected(service, tmp_path, relative):
    directory, source = setup_source(service, tmp_path)
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PORO\n1*0.2 /\n")
    parent = relative.rpartition("/")[0]
    entry = next(e for e in scan(service, source, path=parent)["entries"] if e["path"] == relative)
    sources = LocalSources(service.store)
    with sources.opened(source["id"], relative) as (fd, _):
        assert entry["file_revision"] == revision(os.fstat(fd))
        assert entry["size_bytes"] == os.fstat(fd).st_size
    pid = service.invoke("project_create", dict(name="Revision", vertical_datum="TEST"))["id"]
    request = dict(
        project_id=pid, source_id=source["id"], path=relative, file_revision=entry["file_revision"]
    )
    assert service.invoke("source_upload", request)["source"]["file_revision"] == entry["file_revision"]
    path.write_bytes(b"PORO\n2*0.3 /\nchanged\n")
    with pytest.raises(DomainError) as error:
        service.invoke("source_upload", request)
    assert error.value.code == "SOURCE_CHANGED"
    changed = next(e for e in scan(service, source, path=parent)["entries"] if e["path"] == relative)
    assert changed["file_revision"] != entry["file_revision"]
