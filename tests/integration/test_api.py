from fastapi.testclient import TestClient

from opensubsurface.api.app import create_app


def test_api_contracts_and_origin_guard(service):
    with TestClient(create_app(service=service, with_ui=False)) as client:
        response = client.post(
            "/api/v1/projects", json=dict(name="API", crs="LOCAL_METRIC", vertical_datum="TEST")
        )
        assert response.status_code == 200
        pid = response.json()["id"]
        bad = client.post("/api/v1/projects", json=dict(name="Bad", vertical_datum="unknown"))
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "MISSING_DATUM"
        assert client.get("/api/v1/projects", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/v1/projects", headers={"Host": "evil.example"}).status_code == 400
        submit = client.post(
            "/api/v1/operations/model_build", json=dict(project_id=pid, horizontal_assumption=True)
        )
        assert submit.status_code == 202
        result = service.wait(submit.json())
        assert client.get(f"/api/v1/projects/{pid}/artifacts/{result['id']}/1").status_code == 200
        schema = client.get("/openapi.json").json()
        assert "/api/v1/operations/volumetrics_calculate" in schema["paths"]
        assert schema["info"]["title"] == "Kanysh Basic"


def test_all_endpoints_auth_including_ui(service, monkeypatch):
    monkeypatch.setenv("OPENSUBSURFACE_TOKEN", "test-token")
    with TestClient(create_app(service=service, with_ui=True)) as client:
        assert client.get("/api/v1/projects").status_code == 401
        assert client.get("/app/", follow_redirects=False).status_code == 303
        assert (
            client.get("/api/v1/projects", headers={"Authorization": "Bearer test-token"}).status_code == 200
        )
        assert client.post("/login", data={"token": "wrong"}).status_code == 401
        assert client.post("/login", data={"token": "test-token"}, follow_redirects=False).status_code == 303
        assert client.get("/api/v1/projects").status_code == 200
