"""Audit log emission on container lifecycle actions."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _get_audit_logs(client: TestClient) -> list[dict]:
    response = client.get("/api/audit/log")
    response.raise_for_status()
    return response.json()["entries"]


def test_deploy_creates_audit_entry(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/containers/deploy",
        json={
            "image": "redis:7",
            "container_port": 6379,
            "container_name": "audit-test-deploy",
        },
    )
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    deploy_logs = [l for l in logs if l["action"] == "container.deploy"]
    assert len(deploy_logs) >= 1
    last = deploy_logs[-1]
    assert last["target_type"] == "container"
    assert last["details"] is not None
    assert last["details"]["image"] == "redis:7"


def test_start_creates_audit_entry(api_client: TestClient) -> None:
    response = api_client.post("/api/containers/cid-1/start")
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    assert any(l["action"] == "container.start" for l in logs)


def test_stop_creates_audit_entry(api_client: TestClient) -> None:
    response = api_client.post("/api/containers/cid-1/stop")
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    assert any(l["action"] == "container.stop" for l in logs)


def test_restart_creates_audit_entry(api_client: TestClient) -> None:
    response = api_client.post("/api/containers/cid-1/restart")
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    assert any(l["action"] == "container.restart" for l in logs)


def test_remove_creates_audit_entry(api_client: TestClient) -> None:
    response = api_client.delete("/api/containers/cid-1")
    assert response.status_code == 204
    logs = _get_audit_logs(api_client)
    assert any(l["action"] == "container.remove" for l in logs)


def test_exec_creates_audit_entry(
    api_client: TestClient, auth_token: str
) -> None:
    with api_client.websocket_connect(
        f"/api/containers/cid-1/exec/ws?access_token={auth_token}"
    ) as websocket:
        websocket.receive_bytes()
    logs = _get_audit_logs(api_client)
    exec_logs = [l for l in logs if l["action"] == "container.exec"]
    assert len(exec_logs) == 1
    assert exec_logs[0]["target_id"] == "cid-1"
