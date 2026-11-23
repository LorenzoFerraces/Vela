"""Tests for the project compute-quota API."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.db.models import Project


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


async def test_explicit_null_clears_stored_compute_limit(
    api_client: TestClient, db_session_factory, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "20")
    project_id = _personal_project_id(api_client)
    assert api_client.patch(
        f"/api/projects/{project_id}/compute-quota",
        json={"max_running_containers": 3},
    ).status_code == 200

    response = api_client.patch(
        f"/api/projects/{project_id}/compute-quota",
        json={"max_running_containers": None},
    )
    assert response.status_code == 200, response.text
    assert response.json()["max_running_containers"] is None

    async with db_session_factory() as session:
        project = await session.get(Project, UUID(project_id))
        assert project is not None
        assert project.max_running_containers is None


async def test_absent_field_keeps_stored_compute_limit(
    api_client: TestClient, db_session_factory, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "20")
    monkeypatch.setenv("VELA_TEAM_MAX_CPU_MILLICORES", "20")
    project_id = _personal_project_id(api_client)
    assert api_client.patch(
        f"/api/projects/{project_id}/compute-quota",
        json={"max_running_containers": 3},
    ).status_code == 200

    response = api_client.patch(
        f"/api/projects/{project_id}/compute-quota",
        json={"max_cpu_millicores": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["max_running_containers"] == 3
    assert body["max_cpu_millicores"] == 5

    async with db_session_factory() as session:
        project = await session.get(Project, UUID(project_id))
        assert project is not None
        assert project.max_running_containers == 3
        assert project.max_cpu_millicores == 5
