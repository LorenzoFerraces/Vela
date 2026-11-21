from fastapi.testclient import TestClient


def test_by_name_resolves_own_container(api_client: TestClient) -> None:
    response = api_client.get("/api/containers/by-name/vela-test")
    assert response.status_code == 200
    assert response.json()["name"] == "vela-test"


def test_by_name_unknown_is_not_found(api_client: TestClient) -> None:
    assert api_client.get("/api/containers/by-name/missing").status_code == 404


def test_by_name_requires_auth(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/api/containers/by-name/vela-test").status_code == 401
