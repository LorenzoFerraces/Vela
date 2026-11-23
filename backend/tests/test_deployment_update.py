"""Tests for the deployment config dry-run and PATCH update surface."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.schemas import DeploymentRecordPublic
from app.core.auth.service import get_user_by_id
from app.core.auth.tokens import decode_access_token
from app.core.deploy.deployment_history import load_deploy_config_snapshot
from app.core.enums import RestartPolicy
from app.core.exceptions import TeamComputeQuotaExceededError
from app.core.models import DeployConfig
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


def test_patch_rejects_invalid_restart_policy(api_client: TestClient) -> None:
    deployment_id = _seed_deployment(api_client)

    response = api_client.patch(
        f"/api/deployments/{deployment_id}",
        json={"restart_policy": "bogus"},
    )
    assert response.status_code == 422, response.text


def test_patch_round_trips_valid_restart_policy(
    api_client: TestClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    deployment_id = _seed_deployment(api_client)

    response = api_client.patch(
        f"/api/deployments/{deployment_id}",
        json={"restart_policy": "always"},
    )
    assert response.status_code == 200, response.text
    new_record_id = response.json()["id"]
    container_id = response.json()["container_id"]

    async def load_snapshot() -> DeployConfig:
        async with db_session_factory() as session:
            config = await load_deploy_config_snapshot(session, container_id)
            assert config is not None
            return config

    assert asyncio.run(load_snapshot()).restart_policy == RestartPolicy.ALWAYS

    followup = api_client.post(
        f"/api/deployments/{new_record_id}/dry-run", json={}
    )
    assert followup.status_code == 200, followup.text


def test_patch_response_is_the_created_record(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    deployment_id = _seed_deployment(api_client)
    stale = api_client.get(f"/api/deployments/{deployment_id}").json()

    async def concurrent_head(*args: object, **kwargs: object) -> list[DeploymentRecordPublic]:
        return [DeploymentRecordPublic.model_validate(stale)]

    monkeypatch.setattr(
        "app.api.routes.deployments.deployment_history.list_deployments",
        concurrent_head,
    )
    response = api_client.patch(
        f"/api/deployments/{deployment_id}", json={"env_vars": {"B": "2"}}
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] != stale["id"]
    assert response.json()["id"] == str(_all_records(db_session_factory)[-1].id)


def test_patch_preserves_git_branch_and_build_override(
    api_client: TestClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    deployment_id = _seed_deployment(api_client)

    async def mark_as_git() -> None:
        async with db_session_factory() as session:
            row = (await session.execute(
                select(DeploymentRecord).where(
                    DeploymentRecord.id == uuid.UUID(deployment_id)
                )
            )).scalar_one()
            row.source_kind = "git"
            row.source_ref = "https://github.com/acme/app"
            row.git_branch = "feature-branch"
            row.build_override = {"language": "python"}
            await session.commit()

    asyncio.run(mark_as_git())
    response = api_client.patch(
        f"/api/deployments/{deployment_id}", json={"env_vars": {"B": "2"}}
    )
    assert response.status_code == 200, response.text
    created = _all_records(db_session_factory)[-1]
    assert created.git_branch == "feature-branch"
    assert created.build_override is not None
    assert created.build_override["language"] == "python"


def test_patch_is_quota_gated(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    deployment_id = _seed_deployment(api_client)
    before = len(_all_records(db_session_factory))

    async def over_quota(*args: object, **kwargs: object) -> None:
        raise TeamComputeQuotaExceededError(
            "Team compute quota exceeded for memory bytes"
        )

    monkeypatch.setattr(
        "app.api.routes.deployments.enforce_team_compute_capacity", over_quota
    )
    response = api_client.patch(
        f"/api/deployments/{deployment_id}", json={"env_vars": {"B": "2"}}
    )
    assert response.status_code == 409, response.text
    assert len(_all_records(db_session_factory)) == before


def test_patch_rejects_config_that_fails_deploy_validation(
    api_client: TestClient,
) -> None:
    deployment_id = _seed_deployment(api_client)
    response = api_client.patch(
        f"/api/deployments/{deployment_id}", json={"cpu_limit": 0}
    )
    assert response.status_code == 422, response.text


def test_viewer_cannot_redeploy_their_deployment(
    integration_app: Any,
    register_user_client: Any,
) -> None:
    with TestClient(integration_app) as owner_client, TestClient(integration_app) as viewer_client:
        owner_token = register_user_client(
            "patch-owner@example.com", role="instructor"
        )
        owner_client.headers.update({"Authorization": f"Bearer {owner_token}"})
        project_id = owner_client.get("/api/projects/").json()[0]["id"]

        viewer_email = "patch-viewer@example.com"
        viewer_token = register_user_client(viewer_email)
        viewer_client.headers.update({"Authorization": f"Bearer {viewer_token}"})
        viewer_id = str(decode_access_token(viewer_token).user_id)

        invitation = owner_client.post(
            f"/api/projects/{project_id}/invitations",
            json={"email": viewer_email, "role": "operator"},
        )
        assert invitation.status_code == 201, invitation.text
        incoming = viewer_client.get("/api/projects/invitations/incoming").json()
        invitation_id = next(
            row["id"] for row in incoming if row["project_id"] == project_id
        )
        assert viewer_client.post(
            f"/api/projects/invitations/{invitation_id}/accept"
        ).status_code == 200

        accepted = viewer_client.post(
            "/api/containers/run",
            json={
                "source_kind": "image",
                "image_ref": "nginx:alpine",
                "project_id": project_id,
            },
        )
        assert accepted.status_code == 202, accepted.text
        job = wait_for_deploy(viewer_client, accepted.json()["job_id"])
        assert job["status"] == "succeeded", job
        deployment_id = viewer_client.get("/api/deployments/").json()[0]["id"]

        downgrade = owner_client.patch(
            f"/api/projects/{project_id}/members/{viewer_id}",
            json={"role": "viewer"},
        )
        assert downgrade.status_code == 200, downgrade.text

        response = viewer_client.patch(
            f"/api/deployments/{deployment_id}", json={"env_vars": {"B": "2"}}
        )
        assert response.status_code == 403, response.text
