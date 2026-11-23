"""Tests for deployment history and AI pre-fill settings."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.auth.service import get_user_by_id
from app.core.containers.docker_orchestrator import VELA_OWNER_LABEL
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.projects.repository import get_personal_project_id
from app.core.secret_store import create_secret
from tests.test_deploy_jobs import wait_for_deploy


def test_ai_prefill_defaults(api_client: TestClient) -> None:
    response = api_client.get("/api/settings/ai-prefill")
    assert response.status_code == 200
    body = response.json()
    assert body["git_branch"] is True
    assert body["container_port"] is True
    assert body["env_vars"] is True


def test_ai_prefill_patch(api_client: TestClient) -> None:
    response = api_client.patch(
        "/api/settings/ai-prefill",
        json={"container_port": False},
    )
    assert response.status_code == 200
    assert response.json()["container_port"] is False
    assert response.json()["git_branch"] is True


def test_analyze_git_source_e2e_fixture(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_E2E", "1")
    response = api_client.post(
        "/api/builder/analyze-source",
        json={
            "git_url": "https://github.com/org/repo.git",
            "git_branch": "main",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["container_port"] == 5173
    assert body["summary_hint"]


def test_run_creates_deployment_record(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    db_session_factory,
    test_user_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")

    async def seed_secret() -> None:
        async with db_session_factory() as session:
            user = await get_user_by_id(session, test_user_id)
            assert user is not None
            project_id = await get_personal_project_id(session, user)
            await create_secret(
                session,
                owner_user_id=None,
                project_id=project_id,
                name="DB_URL",
                value="postgres://real",
            )

    asyncio.run(seed_secret())

    response = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "public_route": True,
            "container_port": 80,
            "env_vars": {"FOO": "bar", "DB": "secret://DB_URL@latest"},
            "command": ["nginx", "-g", "daemon off;"],
        },
    )
    assert response.status_code == 202, response.text
    job = wait_for_deploy(api_client, response.json()["job_id"])
    assert job["status"] == "succeeded", job

    listed = api_client.get("/api/deployments/")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) >= 1
    latest = rows[0]
    assert latest["env_vars"] == {
        "FOO": "<REDACTED>",
        "DB": "secret://DB_URL@latest",
    }
    assert latest["command"] == ["nginx", "-g", "daemon off;"]
    assert latest["source_kind"] == "image"
    assert fake_orchestrator.last_deploy_config is not None
    assert fake_orchestrator.last_deploy_config.labels.get(VELA_OWNER_LABEL)
    assert fake_orchestrator.last_deploy_config.env_vars["DB"] == "postgres://real"
    assert fake_orchestrator.last_deploy_config.env_vars["FOO"] == "bar"


def test_deployment_diff(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    monkeypatch.setenv("VELA_PUBLIC_URL_SCHEME", "https")

    first = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "public_route": True,
            "env_vars": {"A": "1"},
        },
    )
    assert first.status_code == 202
    first_job = wait_for_deploy(api_client, first.json()["job_id"])
    assert first_job["status"] == "succeeded"

    second = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "public_route": True,
            "env_vars": {"A": "2", "B": "3"},
        },
    )
    assert second.status_code == 202
    second_job = wait_for_deploy(api_client, second.json()["job_id"])
    assert second_job["status"] == "succeeded"

    rows = api_client.get("/api/deployments/").json()
    assert len(rows) >= 2
    left_id = rows[1]["id"]
    right_id = rows[0]["id"]
    diff = api_client.get(f"/api/deployments/{left_id}/diff/{right_id}")
    assert diff.status_code == 200
    env_diff = diff.json()["env"]
    assert env_diff["added"] == {"B": "<REDACTED>"}
    assert env_diff["changed"] == {}
