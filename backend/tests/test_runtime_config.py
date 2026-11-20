from fastapi.testclient import TestClient


def test_runtime_config_exposes_exec_session_cap(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/runtime-config")
    assert response.status_code == 200
    assert response.json()["exec_max_session_seconds"] >= 1
