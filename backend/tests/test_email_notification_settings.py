"""Integration tests for email notification settings API."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_email_notifications_get_defaults(api_client: TestClient) -> None:
    response = api_client.get("/api/settings/email-notifications")
    assert response.status_code == 200
    body = response.json()
    assert body["alerts_enabled"] is True
    assert set(body["alert_types"]) == {"stop", "failure", "unhealthy"}
    assert body["alert_frequency"] == "immediate"
    assert body["email"] == "user@example.com"


def test_email_notifications_patch_persists(api_client: TestClient) -> None:
    response = api_client.patch(
        "/api/settings/email-notifications",
        json={"alerts_enabled": False, "alert_types": ["stop"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["alerts_enabled"] is False
    assert body["alert_types"] == ["stop"]

    again = api_client.get("/api/settings/email-notifications")
    assert again.status_code == 200
    assert again.json()["alerts_enabled"] is False


def test_email_notifications_history_empty(api_client: TestClient) -> None:
    response = api_client.get("/api/settings/email-notifications/history")
    assert response.status_code == 200
    assert response.json() == []


def test_monitoring_status(api_client: TestClient) -> None:
    response = api_client.get("/api/settings/monitoring/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["interval_seconds"] == 15
    assert body["total_containers_tracked"] >= 0
