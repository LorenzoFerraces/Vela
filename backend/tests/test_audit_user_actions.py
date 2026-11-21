"""Audit log emission on user profile actions."""

from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient


def _get_audit_logs(client: TestClient) -> list[dict]:
    """Fetch the current audit log entries."""
    response = client.get("/api/audit/log")
    response.raise_for_status()
    return response.json()["entries"]


def test_profile_update_creates_audit_entry(api_client: TestClient) -> None:
    """Updating the profile writes a user.profile_update audit entry."""
    response = api_client.patch(
        "/api/users/me",
        json={"display_name": "Test User"},
    )
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    assert any(entry["action"] == "user.profile_update" for entry in logs)


def test_avatar_upload_creates_audit_entry(api_client: TestClient) -> None:
    """Uploading an avatar writes a user.avatar_upload audit entry."""
    png = BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    response = api_client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.png", png, "image/png")},
    )
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    assert any(entry["action"] == "user.avatar_upload" for entry in logs)


def test_avatar_removed_creates_audit_entry(api_client: TestClient) -> None:
    """Deleting the avatar writes a user.avatar_removed audit entry."""
    response = api_client.delete("/api/users/me/avatar")
    assert response.status_code == 200
    logs = _get_audit_logs(api_client)
    assert any(entry["action"] == "user.avatar_removed" for entry in logs)
