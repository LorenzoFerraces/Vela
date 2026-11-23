"""Tests for the deployment config dry-run and PATCH update surface."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth.service import get_user_by_id
from app.core.projects.repository import get_personal_project_id
from app.core.secret_store import create_secret
from app.db.models import DeploymentRecord
from tests.test_deploy_jobs import wait_for_deploy


def _seed_deployment(api_client: TestClient) -> str:
    accepted = api_client.post(
        "/api/containers/run",
        json={
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "env_vars": {"A": "1"},
        },
    )
    assert accepted.status_code == 202, accepted.text
    job = wait_for_deploy(api_client, accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    rows = api_client.get("/api/deployments/").json()
    assert rows
    return rows[0]["id"]


def _all_records(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> list[DeploymentRecord]:
    async def load() -> list[DeploymentRecord]:
        async with db_session_factory() as session:
            result = await session.execute(
                select(DeploymentRecord).order_by(DeploymentRecord.created_at)
            )
            return list(result.scalars().all())

    return asyncio.run(load())


def test_dry_run_returns_non_secret_config_diff(api_client: TestClient) -> None:
    deployment_id = _seed_deployment(api_client)

    response = api_client.post(
        f"/api/deployments/{deployment_id}/dry-run",
        json={"env_vars": {"B": "2"}, "command": ["node", "app.js"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["env"]["added"]["B"] == "2"
    assert body["config"]["command"] == ["node", "app.js"]
    assert "secret" not in str(body["config"])


def test_identity_change_requires_recreate(api_client: TestClient) -> None:
    deployment_id = _seed_deployment(api_client)

    response = api_client.patch(
        f"/api/deployments/{deployment_id}",
        json={"image": "other-image"},
    )
    assert response.status_code == 400, response.text
    assert "image" in response.json()["detail"]


def test_patch_writes_a_new_history_entry(
    api_client: TestClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    deployment_id = _seed_deployment(api_client)
    before = _all_records(db_session_factory)
    assert len(before) == 1

    response = api_client.patch(
        f"/api/deployments/{deployment_id}",
        json={"env_vars": {"B": "2"}},
    )
    assert response.status_code == 200, response.text

    after = _all_records(db_session_factory)
    assert len(after) == 2
    assert after[-1].id != before[-1].id
    assert after[-1].env_vars == {"B": "<REDACTED>"}


def test_patch_rejects_managed_label_edits(api_client: TestClient) -> None:
    deployment_id = _seed_deployment(api_client)

    response = api_client.patch(
        f"/api/deployments/{deployment_id}",
        json={"labels": {"vela.owner_id": "someone-else"}},
    )
    assert response.status_code == 400, response.text
    assert "vela.owner_id" in response.json()["detail"]


def test_patch_resolves_secret_refs_only_for_orchestrator(
    api_client: TestClient,
    fake_orchestrator,
    db_session_factory: async_sessionmaker[AsyncSession],
    test_user_id,
) -> None:
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
    deployment_id = _seed_deployment(api_client)

    response = api_client.patch(
        f"/api/deployments/{deployment_id}",
        json={"env_vars": {"DB": "secret://DB_URL@latest"}},
    )
    assert response.status_code == 200, response.text
    assert fake_orchestrator.last_deploy_config is not None
    assert fake_orchestrator.last_deploy_config.env_vars["DB"] == "postgres://real"
    assert _all_records(db_session_factory)[-1].env_vars == {
        "DB": "secret://DB_URL@latest"
    }
