"""Tests for the project compute-quota API."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient


def _personal_project_id(client: TestClient) -> str:
    return next(
        project["id"]
        for project in client.get("/api/projects/").json()
        if project["is_personal"]
    )


def test_owner_can_set_compute_quota_within_ceiling(
    api_client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "20")
    project_id = _personal_project_id(api_client)

    response = api_client.patch(
        f"/api/projects/{project_id}/compute-quota",
        json={"max_running_containers": 5},
    )
    assert response.status_code == 200, response.text
    assert response.json()["max_running_containers"] == 5


def test_member_cannot_set_compute_quota(other_user_client: TestClient) -> None:
    response = other_user_client.patch(
        f"/api/projects/{uuid4()}/compute-quota",
        json={"max_running_containers": 5},
    )
    assert response.status_code in (403, 404)


def test_quota_above_ceiling_is_rejected(
    api_client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "3")
    project_id = _personal_project_id(api_client)

    response = api_client.patch(
        f"/api/projects/{project_id}/compute-quota",
        json={"max_running_containers": 5},
    )
    assert response.status_code == 400
    assert "platform ceiling" in response.json()["detail"]


def test_get_compute_quota_returns_usage_and_ceiling(
    api_client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "7")
    project_id = _personal_project_id(api_client)

    response = api_client.get(f"/api/projects/{project_id}/compute-quota")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["max_running_containers"] is None
    assert body["used_running_containers"] == 0
    assert body["used_cpu_millicores"] == 0
    assert body["used_memory_bytes"] == 0
    assert body["used_deploys_per_hour"] == 0
    assert body["platform_ceiling"]["running_containers"] == 7


def test_compute_quota_requires_authentication(
    anonymous_client: TestClient,
) -> None:
    response = anonymous_client.get(f"/api/projects/{uuid4()}/compute-quota")
    assert response.status_code == 401
