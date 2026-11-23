"""F10 — PR preview deploys, TTL GC and the preview secret guard."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.exceptions import PreviewSecretForbiddenError
from app.core.previews import collect_expired_previews, preview_deploy_config
from app.db.models import GitHubAppInstall, GitHubWebhookConfig, PreviewDeploy, User

WEBHOOK_SECRET = "preview-hook-secret"


def _headers(payload: dict, event: str, delivery_id: str) -> dict[str, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    digest = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": event,
        "content-type": "application/json",
    }


def test_preview_config_is_capped_and_namespaced() -> None:
    config = preview_deploy_config(
        repo_full_name="org/repo", pr_number=7, head_sha="abc123",
        image="nginx:latest", env_vars={"PUBLIC_URL": "https://example.test"},
        ttl_seconds=600,
    )
    assert config.name is not None
    assert config.name.startswith("pr-7-")
    assert config.cpu_limit is not None and config.cpu_limit <= 0.5
    assert config.memory_limit is not None and config.memory_limit <= 512
    assert config.public_route is True
    assert "PREVIEW=true" in "=".join(f"{k}={v}" for k, v in config.labels.items())


def test_preview_rejects_secret_reference() -> None:
    with pytest.raises(PreviewSecretForbiddenError):
        preview_deploy_config(
            repo_full_name="org/repo", pr_number=8, head_sha="def", image="nginx",
            env_vars={"DB": "secret://DB_URL"}, ttl_seconds=600,
        )


def test_collect_expired_previews_removes_expired_rows(db_session_factory) -> None:
    async def run() -> dict[str, object]:
        now = datetime.now(UTC)
        async with db_session_factory() as session:
            session.add(
                PreviewDeploy(
                    project_id=uuid.uuid4(), repo_full_name="org/repo", pr_number=11,
                    head_sha="aaa", container_id="container-expired",
                    container_name="pr-11-aaa", route_host="pr-11.example.test",
                    expires_at=now - timedelta(seconds=1),
                )
            )
            session.add(
                PreviewDeploy(
                    project_id=uuid.uuid4(), repo_full_name="org/repo", pr_number=12,
                    head_sha="bbb", container_id="container-live",
                    container_name="pr-12-bbb", route_host="pr-12.example.test",
                    expires_at=now + timedelta(hours=1),
                )
            )
            await session.commit()

        orchestrator = AsyncMock()
        router = AsyncMock()
        async with db_session_factory() as session:
            swept = await collect_expired_previews(session, orchestrator, router)
        async with db_session_factory() as session:
            rows = (await session.execute(
                select(PreviewDeploy).order_by(PreviewDeploy.pr_number)
            )).scalars().all()
        return {
            "swept": swept,
            "removed": [call.args[0] for call in orchestrator.remove.await_args_list],
            "routes": [call.args[0] for call in router.remove_route.await_args_list],
            "statuses": [row.status for row in rows],
        }

    result = asyncio.run(run())
    assert result["swept"] == 1
    assert result["removed"] == ["container-expired"]
    assert result["routes"] == ["pr-11-aaa"]
    assert result["statuses"] == ["expired", "pending"]


def test_webhook_creates_preview_and_teardown_closes_it(
    api_client, db_session_factory, seeded_user
) -> None:
    project_id = uuid.uuid4()

    async def seed() -> None:
        from app.core.security.secrets import encrypt_secret

        async with db_session_factory() as session:
            session.add(
                GitHubAppInstall(
                    app_id="123", private_key_encrypted=encrypt_secret("pem"),
                    webhook_secret_encrypted=encrypt_secret(WEBHOOK_SECRET),
                )
            )
            session.add(
                GitHubWebhookConfig(
                    project_id=project_id, repo_full_name="org/repo", enabled=True,
                    branch_filters=[], preview_enabled=True, preview_ttl_seconds=1800,
                    created_by_user_id=seeded_user.id,
                )
            )
            await session.commit()

    asyncio.run(seed())
    url = f"/webhooks/github/{project_id}"
    payload = {
        "action": "opened",
        "repository": {"full_name": "org/repo"},
        "pull_request": {
            "number": 21,
            "head": {
                "sha": "deadbeefcafe", "ref": "feature", "repo": {"fork": False},
            },
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    assert api_client.post(
        url, content=body, headers=_headers(payload, "pull_request", "pr-open")
    ).json()["status"] == "received"

    async def get_row() -> PreviewDeploy:
        async with db_session_factory() as session:
            return (
                await session.execute(
                    select(PreviewDeploy).where(
                        PreviewDeploy.project_id == project_id,
                        PreviewDeploy.pr_number == 21,
                    )
                )
            ).scalar_one()

    row = asyncio.run(get_row())
    assert row.head_sha == "deadbeefcafe"
    assert row.repo_full_name == "org/repo"
    assert row.expires_at is not None

    closed = {
        "action": "closed",
        "repository": {"full_name": "org/repo"},
        "pull_request": {
            "number": 21,
            "head": {
                "sha": "deadbeefcafe", "ref": "feature", "repo": {"fork": False},
            },
        },
    }
    closed_body = json.dumps(closed, separators=(",", ":")).encode()
    assert api_client.post(
        url, content=closed_body, headers=_headers(closed, "pull_request", "pr-close")
    ).json()["status"] == "received"

    closed_row = asyncio.run(get_row())
    assert closed_row.status == "closed"
    assert closed_row.closed_at is not None


def test_previews_endpoint_returns_member_rows(
    api_client, db_session_factory, seeded_user: User
) -> None:
    from app.core.projects.repository import get_personal_project_id

    async def project_and_seed() -> uuid.UUID:
        async with db_session_factory() as session:
            user = await session.get(User, seeded_user.id)
            assert user is not None
            project_id = await get_personal_project_id(session, user)
            session.add(
                PreviewDeploy(
                    project_id=project_id, repo_full_name="org/repo", pr_number=31,
                    head_sha="cafe", public_url="https://pr-31.example.test/",
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                    status="deployed",
                )
            )
            await session.commit()
            return project_id

    project_id = asyncio.run(project_and_seed())
    entries = api_client.get(f"/api/projects/{project_id}/previews").json()
    assert len(entries) == 1
    assert entries[0]["pr_number"] == 31
    assert entries[0]["public_url"] == "https://pr-31.example.test/"
