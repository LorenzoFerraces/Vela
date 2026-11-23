"""Integration tests for the team showback API and CSV export."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_showback_is_team_scoped_and_reports_resource_time(api_client: TestClient):
    response = api_client.get("/api/metrics/showback")
    assert response.status_code == 200
    body = response.json()
    assert "teams" in body
    for team in body["teams"]:
        assert set(team) >= {"team_name", "cpu_seconds", "memory_gib_hours", "storage_gib_days"}
        assert team["cost_currency"] is None


def test_showback_is_401_for_anonymous(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/api/metrics/showback").status_code == 401


def test_csv_export_has_expected_header(api_client: TestClient) -> None:
    response = api_client.get("/api/metrics/showback/export?month=2026-11")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0] == "team,cpu_seconds,memory_gib_hours,storage_gib_days"
