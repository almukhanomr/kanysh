import pytest

from opensubsurface import __version__
from opensubsurface.errors import DomainError
from opensubsurface.persistence import store as store_module
from opensubsurface.persistence.store import Store


def _project(service):
    return service.invoke("project_create", dict(name="core", vertical_datum="MSL"))


def test_unchanged_blob_is_hashed_once_per_process(service, tmp_path, monkeypatch):
    project = _project(service)
    source = tmp_path / "report.json"
    source.write_text('{"value": 1}', encoding="utf-8")
    obj = service.store.publish(project["id"], "validation", {}, {"report.json": source})
    hashed = []
    original = store_module.file_hash
    monkeypatch.setattr(store_module, "file_hash", lambda path: hashed.append(path) or original(path))

    reference = dict(id=obj["id"], revision=obj["revision"])
    loaded = service.store.object(project["id"], reference)
    service.store.path(loaded, "report.json")
    service.store.object(project["id"], reference)
    assert len(hashed) == 1

    blob = service.store.root / "blobs" / obj["files"]["report.json"]
    blob.write_text('{"value": 2, "tampered": true}', encoding="utf-8")
    with pytest.raises(DomainError) as error:
        service.store.object(project["id"], reference)
    assert error.value.code == "INTEGRITY_ERROR"


def test_new_process_verifies_blobs_again(service, tmp_path, monkeypatch):
    project = _project(service)
    source = tmp_path / "report.json"
    source.write_text("{}", encoding="utf-8")
    obj = service.store.publish(project["id"], "validation", {}, {"report.json": source})
    reference = dict(id=obj["id"], revision=obj["revision"])
    service.store.object(project["id"], reference)

    hashed = []
    original = store_module.file_hash
    monkeypatch.setattr(store_module, "file_hash", lambda path: hashed.append(path) or original(path))
    other = Store(service.store.root)
    try:
        other.object(project["id"], reference)
    finally:
        other.engine.dispose()
    assert len(hashed) == 1


def test_more_than_200_artifacts_are_not_silently_dropped(service):
    project = _project(service)
    for index in range(205):
        service.store.publish(project["id"], "validation", dict(index=index))

    assert len(service.store.list_objects(project["id"])) == 200
    everything = service.store.list_objects(project["id"], limit=None)
    assert sorted(o["summary"]["index"] for o in everything) == list(range(205))

    inspected = service.invoke("project_inspect", dict(project_id=project["id"]))
    assert inspected["object_count"] == 205 and inspected["objects_truncated"] is True
    assert len(inspected["objects"]) == 200
    assert inspected["job_count"] == 0 and inspected["jobs_truncated"] is False


def test_small_project_listing_is_complete(service, demo):
    inspected = service.invoke("project_inspect", dict(project_id=demo["project"]["id"]))
    assert inspected["objects_truncated"] is False and inspected["jobs_truncated"] is False
    assert inspected["object_count"] == len(inspected["objects"])
    assert inspected["job_count"] == len(inspected["jobs"])


def test_api_reports_the_package_version(service):
    from fastapi.testclient import TestClient

    from opensubsurface.api.app import create_app

    app = create_app(service=service, with_mcp=False)
    assert app.version == __version__
    assert TestClient(app).get("/health").json()["version"] == __version__


def test_finished_job_threads_are_released(service, demo):
    jobs = service.store.list_jobs(demo["project"]["id"])
    assert len(jobs) >= 3
    assert len(service.threads) <= 2
