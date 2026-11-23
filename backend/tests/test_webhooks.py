"""Signed GitHub webhook receiver and its configuration APIs."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
