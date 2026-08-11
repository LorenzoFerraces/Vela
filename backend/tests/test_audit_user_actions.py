"""Audit log emission on user profile actions."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _get_audit_logs(client: TestClient) -> list[dict]:
    response = client.get("/api/audit/log")
    response.raise_for_status()
    return response.json()["entries"]


def test_profile_update_creates_audit_entry(api_client: TestClient) -> None:
    response = api_client.patch(
        "/api/users/me",
        json={"display_name": "Test User"},
    )
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    assert any(l["action"] == "user.profile_update" for l in logs)


def test_avatar_upload_creates_audit_entry(api_client: TestClient) -> None:
    from io import BytesIO

    png = BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    response = api_client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.png", png, "image/png")},
    )
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    assert any(l["action"] == "user.avatar_upload" for l in logs)


def test_avatar_removed_creates_audit_entry(api_client: TestClient) -> None:
    response = api_client.delete("/api/users/me/avatar")
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    assert any(l["action"] == "user.avatar_removed" for l in logs)
