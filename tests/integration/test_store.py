import zipfile

import pytest

from opensubsurface.errors import DomainError
from opensubsurface.persistence.store import Store


def project(store):
    return store.create_project(dict(name="Test", crs="LOCAL_METRIC", vertical_datum="TEST", length_unit="m"))


def test_bundle_roundtrip_and_backup(tmp_path):
    a = Store(tmp_path / "a")
    p = project(a)
    data = tmp_path / "sample.json"
    data.write_text('{"data":123}')
    obj = a.publish(p["id"], "dataset", {"units": "m"}, {"data.json": data})
    bundle = tmp_path / "project.zip"
    a.export_project(p["id"], bundle)
    b = Store(tmp_path / "b")
    b.import_project(bundle)
    restored = b.object(p["id"], {"id": obj["id"], "revision": 1})
    assert restored["content_hash"] == obj["content_hash"]
    assert b.path(restored, "data.json").read_text() == data.read_text()
    a.backup(tmp_path / "backup")
    backup = Store(tmp_path / "backup")
    assert backup.object(p["id"], {"id": obj["id"], "revision": 1}) == obj


def test_archive_traversal_and_hash_tamper_rejected(tmp_path):
    store = Store(tmp_path / "store")
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("../escape", "bad")
    with pytest.raises(DomainError, match="Unsafe"):
        store.import_project(path)
    assert store.list_projects() == []
    p = project(store)
    f = tmp_path / "a"
    f.write_text("original")
    obj = store.publish(p["id"], "dataset", {}, {"a": f})
    store.path(obj, "a").write_text("changed")
    with pytest.raises(DomainError, match="integrity"):
        store.object(p["id"], obj)


def test_revisions_immutable_cross_project_and_idempotency(tmp_path):
    store = Store(tmp_path / "data")
    p = project(store)
    other = project(store)
    first = store.publish(p["id"], "model", {"value": 1})
    second = store.publish(p["id"], "model", {"value": 2}, object_id=first["id"])
    assert second["revision"] == 2
    assert store.object(p["id"], first)["summary"]["value"] == 1
    with pytest.raises(DomainError):
        store.object(other["id"], first)
    args = dict(project_id=p["id"], idempotency_key="x", value=1)
    job, created = store.put_job("test", args)
    again, created_again = store.put_job("test", args)
    assert created and not created_again and job["id"] == again["id"]
    with pytest.raises(DomainError, match="Idempotency key"):
        store.put_job("test", dict(args, value=2))
    store.update_job(job["id"], status="succeeded")
    assert store.update_job(job["id"], status="failed")["status"] == "succeeded"
