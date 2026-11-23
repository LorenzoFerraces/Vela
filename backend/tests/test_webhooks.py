"""Signed GitHub webhook receiver and its configuration APIs."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import User


def _headers(payload: dict, secret: str, delivery_id: str) -> dict[str, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": "push",
        "content-type": "application/json",
    }


def test_webhook_rejects_bad_signature(api_client, db_session_factory) -> None:
    import asyncio

    from app.core.security.secrets import encrypt_secret
    from app.db.models import GitHubAppInstall

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(GitHubAppInstall(
                app_id="123", private_key_encrypted=encrypt_secret("pem"),
                webhook_secret_encrypted=encrypt_secret("hook-secret"),
            ))
            await session.commit()

    asyncio.run(seed())
    response = api_client.post("/webhooks/github/00000000-0000-0000-0000-000000000001", content=b"{}", headers={"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Delivery": "d1", "X-GitHub-Event": "push"})
    assert response.status_code == 400


def test_webhook_rejects_non_ascii_signature(api_client, db_session_factory) -> None:
    import asyncio

    from app.core.security.secrets import encrypt_secret
    from app.db.models import GitHubAppInstall

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(
                GitHubAppInstall(
                    app_id="123",
                    private_key_encrypted=encrypt_secret("pem"),
                    webhook_secret_encrypted=encrypt_secret("hook-secret"),
                )
            )
            await session.commit()

    asyncio.run(seed())
    # Raw bytes -> Starlette decodes the header as latin-1 into a non-ASCII str,
    # the case that used to raise TypeError inside hmac.compare_digest.
    response = api_client.post(
        "/webhooks/github/00000000-0000-0000-0000-000000000001",
        content=b"{}",
        headers={
            "X-Hub-Signature-256": b"sha256=\xff\xff",
            "X-GitHub-Delivery": "d-non-ascii",
            "X-GitHub-Event": "push",
        },
    )
    assert response.status_code == 400


def test_webhook_dedups_delivery_ids(api_client, db_session_factory) -> None:
    import asyncio
    import uuid
    from app.core.security.secrets import encrypt_secret
    from app.db.models import GitHubAppInstall, GitHubWebhookConfig

    project_id = uuid.uuid4()

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(GitHubAppInstall(
                app_id="123", private_key_encrypted=encrypt_secret("pem"),
                webhook_secret_encrypted=encrypt_secret("hook-secret"),
            ))
            session.add(GitHubWebhookConfig(
                project_id=project_id, repo_full_name="org/repo", enabled=True,
                branch_filters=[], preview_enabled=False, preview_ttl_seconds=3600,
            ))
            await session.commit()

    asyncio.run(seed())
    payload = {"repository": {"full_name": "org/repo"}, "ref": "refs/heads/main"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = _headers(payload, "hook-secret", "d-up-1")
    url = f"/webhooks/github/{project_id}"
    first = api_client.post(url, content=body, headers=headers)
    second = api_client.post(url, content=body, headers=headers)
    assert first.json()["status"] == "received"
    assert second.json()["status"] == "duplicate"


def test_webhook_unconfigured_app_returns_503(api_client) -> None:
    response = api_client.post(
        "/webhooks/github/00000000-0000-0000-0000-000000000001",
        content=b"{}",
        headers={
            "X-Hub-Signature-256": "sha256=bad",
            "X-GitHub-Delivery": "d-none",
            "X-GitHub-Event": "push",
        },
    )
    assert response.status_code == 503


def test_webhook_ignores_unlisted_repo_and_branch(api_client, db_session_factory) -> None:
    import asyncio

    from app.core.security.secrets import encrypt_secret
    from app.db.models import GitHubAppInstall, GitHubWebhookConfig

    project_id = uuid.uuid4()

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(
                GitHubAppInstall(
                    app_id="123",
                    private_key_encrypted=encrypt_secret("pem"),
                    webhook_secret_encrypted=encrypt_secret("hook-secret"),
                )
            )
            session.add(
                GitHubWebhookConfig(
                    project_id=project_id,
                    repo_full_name="org/repo",
                    enabled=True,
                    branch_filters=["main"],
                    preview_enabled=False,
                    preview_ttl_seconds=3600,
                )
            )
            await session.commit()

    asyncio.run(seed())
    url = f"/webhooks/github/{project_id}"
    other_repo = {"repository": {"full_name": "org/other"}, "ref": "refs/heads/main"}
    other_branch = {"repository": {"full_name": "org/repo"}, "ref": "refs/heads/dev"}
    assert (
        api_client.post(
            url,
            content=json.dumps(other_repo, separators=(",", ":")).encode(),
            headers=_headers(other_repo, "hook-secret", "d-other-repo"),
        ).json()["status"]
        == "ignored"
    )
    assert (
        api_client.post(
            url,
            content=json.dumps(other_branch, separators=(",", ":")).encode(),
            headers=_headers(other_branch, "hook-secret", "d-other-branch"),
        ).json()["status"]
        == "ignored"
    )


def test_app_config_is_admin_only(
    api_client: TestClient, provision_user
) -> None:
    student, token = provision_user("student-webhook@example.com", role="student")
    with TestClient(api_client.app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        assert client.get("/api/settings/github-app").status_code == 403
        assert (
            client.put(
                "/api/settings/github-app",
                json={
                    "app_id": "9",
                    "private_key": "pem",
                    "webhook_secret": "hook-secret",
                },
            ).status_code
            == 403
        )


def test_app_config_stores_secrets_and_returns_metadata_only(
    api_client: TestClient, provision_user
) -> None:
    _, token = provision_user("admin-webhook@example.com", role="admin")
    with TestClient(api_client.app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        put = client.put(
            "/api/settings/github-app",
            json={
                "app_id": "123",
                "slug": "vela-app",
                "private_key": "super-secret-pem",
                "webhook_secret": "super-secret-hook",
            },
        )
        assert put.status_code == 200
        body = put.json()
        assert body["configured"] is True
        assert body["has_private_key"] is True
        assert body["has_webhook_secret"] is True
        assert "super-secret-pem" not in json.dumps(body)
        assert "super-secret-hook" not in json.dumps(body)
        stored = client.get("/api/settings/github-app").json()
        for field in ("configured", "app_id", "slug", "has_private_key", "has_webhook_secret"):
            assert stored[field] == body[field]
        assert stored["connected_at"] is not None


def test_project_webhook_config_requires_owner(
    api_client: TestClient,
    db_session_factory,
    seeded_user,
    provision_user,
) -> None:
    import asyncio

    from app.core.projects.repository import get_personal_project_id

    async def project_id() -> uuid.UUID:
        async with db_session_factory() as session:
            user = await session.get(User, seeded_user.id)
            return await get_personal_project_id(session, user)

    owner_project_id = asyncio.run(project_id())
    url = f"/api/projects/{owner_project_id}/github-webhook"
    _, other_token = provision_user("other-webhook@example.com")
    with TestClient(api_client.app) as client:
        client.headers["Authorization"] = f"Bearer {other_token}"
        assert client.get(url).status_code in (403, 404)
        assert client.put(url, json={"repo_full_name": "org/repo"}).status_code in (
            403,
            404,
        )

    body = {
        "repo_full_name": "org/repo",
        "enabled": True,
        "branch_filters": ["main"],
        "preview_enabled": True,
        "preview_ttl_seconds": 1800,
    }
    put = api_client.put(url, json=body)
    assert put.status_code == 200
    assert put.json()["branch_filters"] == ["main"]
    assert put.json()["preview_ttl_seconds"] == 1800
    assert api_client.get(url).json() == put.json()


def test_project_webhook_deliveries_lists_history(
    api_client: TestClient, db_session_factory, seeded_user
) -> None:
    import asyncio

    from app.core.projects.repository import get_personal_project_id
    from app.db.models import GitHubWebhookDelivery

    async def project_id() -> uuid.UUID:
        async with db_session_factory() as session:
            user = await session.get(User, seeded_user.id)
            return await get_personal_project_id(session, user)

    project_id_value = asyncio.run(project_id())

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(
                GitHubWebhookDelivery(
                    delivery_id="d-history",
                    project_id=project_id_value,
                    repo_full_name="org/repo",
                    event="push",
                    action=None,
                    branch="main",
                    status="received",
                )
            )
            await session.commit()

    asyncio.run(seed())
    entries = api_client.get(
        f"/api/projects/{project_id_value}/github-webhook/deliveries"
    ).json()
    assert len(entries) == 1
    assert entries[0]["delivery_id"] == "d-history"
    assert entries[0]["status"] == "received"


def test_webhook_routes_are_outside_api(api_client: TestClient) -> None:
    paths = cast(FastAPI, api_client.app).openapi()["paths"]
    assert "/webhooks/github/{project_id}" in paths
    assert not any(path.startswith("/api/webhooks") for path in paths)


def test_push_triggers_git_source_deploy(
    api_client, db_session_factory, seeded_user, monkeypatch
) -> None:
    import asyncio

    from app.core.security.secrets import encrypt_secret
    from app.db.models import GitHubAppInstall, GitHubWebhookConfig

    project_id = uuid.uuid4()

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(
                GitHubAppInstall(
                    app_id="123", private_key_encrypted=encrypt_secret("pem"),
                    webhook_secret_encrypted=encrypt_secret("hook-secret"),
                )
            )
            session.add(
                GitHubWebhookConfig(
                    project_id=project_id, repo_full_name="org/repo", enabled=True,
                    branch_filters=["main"], preview_enabled=False,
                    preview_ttl_seconds=3600, created_by_user_id=seeded_user.id,
                )
            )
            await session.commit()

    asyncio.run(seed())
    captured: list[object] = []

    async def fake_token(session, project_id) -> str:
        return "inst-token-push"

    async def capture_spawn(registry, job_id, worker, *worker_args) -> None:
        captured.append(worker_args)

    monkeypatch.setattr("app.api.routes.webhooks.installation_token", fake_token)
    monkeypatch.setattr("app.api.routes.webhooks.spawn_deploy_worker", capture_spawn)

    def push_payload(branch: str) -> dict:
        return {
            "repository": {
                "full_name": "org/repo",
                "clone_url": "https://github.com/org/repo.git",
            },
            "ref": f"refs/heads/{branch}",
            "after": "abc123def456",
        }

    url = f"/webhooks/github/{project_id}"
    ignored = push_payload("dev")
    assert api_client.post(
        url,
        content=json.dumps(ignored, separators=(",", ":")).encode(),
        headers=_headers(ignored, "hook-secret", "push-dev"),
    ).json()["status"] == "ignored"
    assert captured == []

    matching = push_payload("main")
    assert api_client.post(
        url,
        content=json.dumps(matching, separators=(",", ":")).encode(),
        headers=_headers(matching, "hook-secret", "push-main"),
    ).json()["status"] == "received"
    assert len(captured) == 1
    args = captured[0]
    assert isinstance(args, tuple)
    run_body = args[3]
    assert run_body.source_kind == "git"
    assert run_body.git_url == "https://github.com/org/repo.git"
    assert run_body.git_branch == "abc123def456"
    assert args[10] == "inst-token-push"


def test_tag_push_is_ignored_without_branch_filters(
    api_client, db_session_factory, seeded_user, monkeypatch
) -> None:
    import asyncio

    from app.core.security.secrets import encrypt_secret
    from app.db.models import GitHubAppInstall, GitHubWebhookConfig

    project_id = uuid.uuid4()

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(
                GitHubAppInstall(
                    app_id="123", private_key_encrypted=encrypt_secret("pem"),
                    webhook_secret_encrypted=encrypt_secret("hook-secret"),
                )
            )
            session.add(
                GitHubWebhookConfig(
                    project_id=project_id, repo_full_name="org/repo", enabled=True,
                    branch_filters=[], preview_enabled=False,
                    preview_ttl_seconds=3600, created_by_user_id=seeded_user.id,
                )
            )
            await session.commit()

    asyncio.run(seed())
    captured: list[object] = []

    async def fake_token(session, project_id) -> str:
        return "inst-token-push"

    async def capture_spawn(registry, job_id, worker, *worker_args) -> None:
        captured.append(worker_args)

    monkeypatch.setattr("app.api.routes.webhooks.installation_token", fake_token)
    monkeypatch.setattr("app.api.routes.webhooks.spawn_deploy_worker", capture_spawn)

    payload = {
        "repository": {
            "full_name": "org/repo",
            "clone_url": "https://github.com/org/repo.git",
        },
        "ref": "refs/tags/v1",
        "after": "abc123def456",
    }
    response = api_client.post(
        f"/webhooks/github/{project_id}",
        content=json.dumps(payload, separators=(",", ":")).encode(),
        headers=_headers(payload, "hook-secret", "push-tag"),
    )
    assert response.json()["status"] == "ignored"
    assert captured == []


def test_push_quota_gates_block_deploy(
    api_client, db_session_factory, seeded_user, monkeypatch
) -> None:
    import asyncio

    from app.core.exceptions import (
        TeamComputeQuotaExceededError,
        TeamStorageQuotaExceededError,
    )
    from app.core.security.secrets import encrypt_secret
    from app.db.models import (
        GitHubAppInstall,
        GitHubWebhookConfig,
        GitHubWebhookDelivery,
    )

    project_id = uuid.uuid4()

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(
                GitHubAppInstall(
                    app_id="123", private_key_encrypted=encrypt_secret("pem"),
                    webhook_secret_encrypted=encrypt_secret("hook-secret"),
                )
            )
            session.add(
                GitHubWebhookConfig(
                    project_id=project_id, repo_full_name="org/repo", enabled=True,
                    branch_filters=[], preview_enabled=False,
                    preview_ttl_seconds=3600, created_by_user_id=seeded_user.id,
                )
            )
            await session.commit()

    asyncio.run(seed())
    captured: list[object] = []

    async def fake_token(session, project_id) -> str:
        return "inst-token-push"

    async def capture_spawn(registry, job_id, worker, *worker_args) -> None:
        captured.append(worker_args)

    monkeypatch.setattr("app.api.routes.webhooks.installation_token", fake_token)
    monkeypatch.setattr("app.api.routes.webhooks.spawn_deploy_worker", capture_spawn)

    payload = {
        "repository": {
            "full_name": "org/repo",
            "clone_url": "https://github.com/org/repo.git",
        },
        "ref": "refs/heads/main",
        "after": "abc123def456",
    }
    url = f"/webhooks/github/{project_id}"
    body = json.dumps(payload, separators=(",", ":")).encode()

    async def over_compute(*args, **kwargs) -> None:
        raise TeamComputeQuotaExceededError("Team compute quota exceeded for running containers")

    monkeypatch.setattr(
        "app.api.routes.webhooks.enforce_team_compute_capacity", over_compute
    )
    assert api_client.post(
        url, content=body, headers=_headers(payload, "hook-secret", "push-compute-quota")
    ).json() == {"status": "failed"}

    async def restore_compute(*args, **kwargs) -> None:
        return None

    async def over_storage(*args, **kwargs) -> None:
        raise TeamStorageQuotaExceededError("Team storage quota exceeded")

    monkeypatch.setattr(
        "app.api.routes.webhooks.enforce_team_compute_capacity", restore_compute
    )
    monkeypatch.setattr(
        "app.api.routes.webhooks.enforce_team_storage_capacity", over_storage
    )
    assert api_client.post(
        url, content=body, headers=_headers(payload, "hook-secret", "push-storage-quota")
    ).json() == {"status": "failed"}
    assert captured == []

    async def delivery_errors() -> list[tuple[str, str | None]]:
        async with db_session_factory() as session:
            rows = (await session.execute(
                select(GitHubWebhookDelivery).where(
                    GitHubWebhookDelivery.delivery_id.in_(
                        ["push-compute-quota", "push-storage-quota"]
                    )
                )
            )).scalars().all()
            return [(row.status, row.error) for row in rows]

    assert all("quota" in (error or "").lower() for _, error in asyncio.run(delivery_errors()))
    assert all(status == "failed" for status, _ in asyncio.run(delivery_errors()))

