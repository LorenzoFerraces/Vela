"""F10 — PR preview deploys, TTL GC and the preview secret guard."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.core.exceptions import (
    ContainerNotFoundError,
    PreviewSecretForbiddenError,
    RouteNotFoundError,
    TeamComputeQuotaExceededError,
)
from app.core.previews import collect_expired_previews, preview_deploy_config
from app.db.models import (
    GitHubAppInstall,
    GitHubWebhookConfig,
    GitHubWebhookDelivery,
    PreviewDeploy,
    User,
)

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


def _stub_preview_worker(monkeypatch) -> dict[str, object]:
    """Capture the worker invoked by the webhook without running a real build."""
    captured: dict[str, object] = {}

    async def fake_token(session, project_id) -> str:
        return "inst-token-xyz"

    async def fake_spawn(registry, job_id, worker, *worker_args) -> None:
        captured["worker"] = worker
        captured["args"] = worker_args

    monkeypatch.setattr("app.api.routes.webhooks.installation_token", fake_token)
    monkeypatch.setattr("app.api.routes.webhooks.spawn_deploy_worker", fake_spawn)
    return captured


def _seed_webhook(db_session_factory, project_id, user_id) -> None:
    from app.core.security.secrets import encrypt_secret

    async def seed() -> None:
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
                    created_by_user_id=user_id,
                )
            )
            await session.commit()

    asyncio.run(seed())


def _pr_payload(action: str, sha: str, ref: str) -> tuple[dict, bytes]:
    payload = {
        "action": action,
        "repository": {"full_name": "org/repo"},
        "pull_request": {
            "number": 21,
            "head": {
                "sha": sha,
                "ref": ref,
                "repo": {"fork": False, "clone_url": "https://github.com/org/repo.git"},
            },
        },
    }
    return payload, json.dumps(payload, separators=(",", ":")).encode()


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
    api_client, db_session_factory, seeded_user, monkeypatch
) -> None:
    project_id = uuid.uuid4()
    _stub_preview_worker(monkeypatch)
    _seed_webhook(db_session_factory, project_id, seeded_user.id)
    url = f"/webhooks/github/{project_id}"
    payload, body = _pr_payload("opened", "deadbeefcafe", "feature")
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

    closed, closed_body = _pr_payload("closed", "deadbeefcafe", "feature")
    assert api_client.post(
        url, content=closed_body, headers=_headers(closed, "pull_request", "pr-close")
    ).json()["status"] == "received"

    closed_row = asyncio.run(get_row())
    assert closed_row.status == "closed"
    assert closed_row.closed_at is not None


def test_webhook_deploys_pr_head_with_installation_token(
    api_client, db_session_factory, seeded_user, monkeypatch
) -> None:
    project_id = uuid.uuid4()
    captured = _stub_preview_worker(monkeypatch)
    _seed_webhook(db_session_factory, project_id, seeded_user.id)

    payload, body = _pr_payload("opened", "deadbeefcafe", "feature/payments")
    assert api_client.post(
        f"/webhooks/github/{project_id}",
        content=body,
        headers=_headers(payload, "pull_request", "pr-token-open"),
    ).json()["status"] == "received"

    args = captured["args"]
    assert isinstance(args, tuple)
    run_body = args[3]
    assert run_body.source_kind == "git"
    assert run_body.git_url == "https://github.com/org/repo.git"
    assert run_body.git_branch == "feature/payments"
    assert run_body.container_name == "pr-21-deadbeef"
    assert run_body.env_vars["PREVIEW"] == "true"
    assert run_body.cpu_limit == 0.5
    assert run_body.memory_limit == 512
    assert args[10] == "inst-token-xyz"  # installation token, no PAT fallback
    assert args[11] == "pr-"  # preview route prefix


def test_preview_worker_delegates_to_source_worker(
    db_session_factory, monkeypatch
) -> None:
    from app.api.routes import webhooks
    from app.api.schemas import RunFromSourceRequest

    forwarded: dict[str, object] = {}

    async def fake_source_worker(
        registry, job_id, session_factory, body, project_id, resolved_volumes,
        user_id, orchestrator, traffic_router, image_builder,
        access_token, route_label_prefix,
    ) -> None:
        forwarded["body"] = body
        forwarded["token"] = access_token
        forwarded["prefix"] = route_label_prefix

    monkeypatch.setattr(webhooks, "_run_container_deploy_worker", fake_source_worker)
    registry = AsyncMock()
    registry.get = AsyncMock(return_value=None)
    body = RunFromSourceRequest(
        source_kind="git", git_url="https://github.com/org/repo.git", git_branch="main"
    )
    asyncio.run(
        webhooks._run_preview_worker(
            registry, "job", db_session_factory, body, uuid.uuid4(), [],
            uuid.uuid4(), AsyncMock(), AsyncMock(), AsyncMock(),
            "inst-token-xyz", "pr-", uuid.uuid4(),
        )
    )
    assert forwarded["body"] is body
    assert forwarded["token"] == "inst-token-xyz"
    assert forwarded["prefix"] == "pr-"


def test_synchronize_previews_teardown_then_redeploy(
    api_client, db_session_factory, seeded_user, monkeypatch, fake_orchestrator
) -> None:
    project_id = uuid.uuid4()
    captured = _stub_preview_worker(monkeypatch)
    _seed_webhook(db_session_factory, project_id, seeded_user.id)

    async def seed_preview() -> None:
        async with db_session_factory() as session:
            session.add(
                PreviewDeploy(
                    project_id=project_id, repo_full_name="org/repo", pr_number=21,
                    head_sha="oldsha123", container_id="old-container-id",
                    container_name="pr-21-oldsha12", route_host="old.example.test",
                    public_url="https://old.example.test/",
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                    status="deployed",
                )
            )
            await session.commit()

    asyncio.run(seed_preview())
    removed: list[str] = []

    async def spy_remove(container_id: str, *, force: bool = False) -> None:
        removed.append(container_id)

    monkeypatch.setattr(fake_orchestrator, "remove", spy_remove)
    payload, body = _pr_payload("synchronize", "newsha456", "feature/new")
    assert api_client.post(
        f"/webhooks/github/{project_id}",
        content=body,
        headers=_headers(payload, "pull_request", "pr-sync"),
    ).json()["status"] == "received"

    assert removed == ["old-container-id"]
    args = captured["args"]
    assert isinstance(args, tuple)
    assert args[3].git_url == "https://github.com/org/repo.git"
    assert args[3].git_branch == "feature/new"
    assert args[10] == "inst-token-xyz"

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
    assert row.head_sha == "newsha456"
    assert row.status == "pending"
    assert row.closed_at is None
    assert row.container_id is None
    assert row.container_name is None
    assert row.route_host is None
    assert row.public_url is None


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


def test_preview_deploy_then_close_removes_route_by_container_name(
    api_client, db_session_factory, seeded_user, monkeypatch, noop_router,
    fake_orchestrator,
) -> None:
    from app.core.enums import BuildStrategy, SupportedLanguage
    from app.core.models import BuildResult, ProjectInfo

    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "example.test")

    async def fake_token(session, project_id) -> str:
        return "inst-token-xyz"

    monkeypatch.setattr("app.api.routes.webhooks.installation_token", fake_token)

    async def inline_spawn(registry, job_id, worker, *worker_args) -> None:
        await worker(*worker_args)

    monkeypatch.setattr("app.api.routes.webhooks.spawn_deploy_worker", inline_spawn)

    async def fake_build(self, source, *, tag, access_token=None, override=None, on_phase=None):
        assert access_token == "inst-token-xyz"
        assert source.git_url == "https://github.com/org/repo.git"
        return BuildResult(
            image_id="sha256:fake", image_tag=tag,
            strategy=BuildStrategy.GENERATED_DOCKERFILE, build_log="",
            project_info=ProjectInfo(language=SupportedLanguage.PYTHON),
        )

    monkeypatch.setattr(
        "app.core.build.default_image_builder.DefaultImageBuilder.build_from_source",
        fake_build,
    )

    removed_containers: list[str] = []
    removed_routes: list[str] = []
    original_container_remove = fake_orchestrator.remove
    original_route_remove = noop_router.remove_route

    async def spy_container_remove(container_id: str, *, force: bool = False) -> None:
        removed_containers.append(container_id)
        await original_container_remove(container_id, force=force)

    async def spy_route_remove(route_id: str) -> None:
        removed_routes.append(route_id)
        await original_route_remove(route_id)

    monkeypatch.setattr(fake_orchestrator, "remove", spy_container_remove)
    monkeypatch.setattr(noop_router, "remove_route", spy_route_remove)

    project_id = uuid.uuid4()
    _seed_webhook(db_session_factory, project_id, seeded_user.id)
    opened, opened_body = _pr_payload("opened", "deadbeefcafe", "feature")
    assert api_client.post(
        f"/webhooks/github/{project_id}",
        content=opened_body,
        headers=_headers(opened, "pull_request", "pr-e2e-open"),
    ).json()["status"] == "received"

    async def get_preview() -> PreviewDeploy:
        async with db_session_factory() as session:
            return (
                await session.execute(
                    select(PreviewDeploy).where(
                        PreviewDeploy.project_id == project_id,
                        PreviewDeploy.pr_number == 21,
                    )
                )
            ).scalar_one()

    preview = asyncio.run(get_preview())
    assert preview.status == "deployed"
    assert preview.container_id is not None
    assert preview.container_name == "pr-21-deadbeef"
    assert preview.route_host is None  # mirror never persisted it — the regression
    route_ids = [route.route_id for route in asyncio.run(noop_router.list_routes())]
    assert preview.container_name in route_ids

    closed, closed_body = _pr_payload("closed", "deadbeefcafe", "feature")
    assert api_client.post(
        f"/webhooks/github/{project_id}",
        content=closed_body,
        headers=_headers(closed, "pull_request", "pr-e2e-close"),
    ).json()["status"] == "received"

    assert removed_containers == [preview.container_id]
    assert removed_routes == [preview.container_name]
    assert asyncio.run(get_preview()).status == "closed"


def test_preview_without_app_link_fails_gracefully(
    api_client, db_session_factory, seeded_user
) -> None:
    project_id = uuid.uuid4()
    _seed_webhook(db_session_factory, project_id, seeded_user.id)
    payload, body = _pr_payload("opened", "aaaabbbbcccc", "feature")
    delivery_id = "pr-no-app-link"
    response = api_client.post(
        f"/webhooks/github/{project_id}",
        content=body,
        headers=_headers(payload, "pull_request", delivery_id),
    )
    assert response.status_code == 200
    assert response.json() == {"status": "failed"}

    async def get_rows() -> tuple[GitHubWebhookDelivery, PreviewDeploy]:
        async with db_session_factory() as session:
            delivery = (
                await session.execute(
                    select(GitHubWebhookDelivery).where(
                        GitHubWebhookDelivery.delivery_id == delivery_id
                    )
                )
            ).scalar_one()
            preview = (
                await session.execute(
                    select(PreviewDeploy).where(
                        PreviewDeploy.project_id == project_id,
                        PreviewDeploy.pr_number == 21,
                    )
                )
            ).scalar_one()
            return delivery, preview

    delivery, preview = asyncio.run(get_rows())
    assert "installation" in (delivery.error or "").lower()
    assert preview.status == "failed"


def test_collect_expired_previews_survives_remove_errors(db_session_factory) -> None:
    async def run() -> dict[str, object]:
        now = datetime.now(UTC)
        async with db_session_factory() as session:
            for pr_number, container, route in (
                (41, "missing-container", "pr-41-missing"),
                (42, "ok-container", "pr-42-ok"),
            ):
                session.add(
                    PreviewDeploy(
                        project_id=uuid.uuid4(), repo_full_name="org/repo",
                        pr_number=pr_number, head_sha="abc",
                        container_id=container, container_name=route,
                        expires_at=now - timedelta(seconds=1),
                    )
                )
            await session.commit()

        orchestrator = AsyncMock()
        orchestrator.remove.side_effect = [
            ContainerNotFoundError("missing-container"), None,
        ]
        router = AsyncMock()
        router.remove_route.side_effect = [
            RouteNotFoundError("pr-41-missing"), None,
        ]
        async with db_session_factory() as session:
            swept = await collect_expired_previews(session, orchestrator, router)
        async with db_session_factory() as session:
            rows = (await session.execute(
                select(PreviewDeploy).order_by(PreviewDeploy.pr_number)
            )).scalars().all()
        return {
            "swept": swept,
            "statuses": [row.status for row in rows],
            "closed": [row.closed_at is not None for row in rows],
        }

    result = asyncio.run(run())
    assert result["swept"] == 2
    assert result["statuses"] == ["expired", "expired"]
    assert result["closed"] == [True, True]


def test_token_network_failure_allows_same_delivery_retry(
    api_client, db_session_factory, seeded_user, monkeypatch
) -> None:
    project_id = uuid.uuid4()
    state = {"fail": True}
    captured: list[object] = []

    async def flaky_token(session, project_id) -> str:
        if state["fail"]:
            raise httpx.ConnectError("connection refused")
        return "inst-token-xyz"

    async def capture_spawn(registry, job_id, worker, *worker_args) -> None:
        captured.append(worker_args)

    monkeypatch.setattr("app.api.routes.webhooks.installation_token", flaky_token)
    monkeypatch.setattr("app.api.routes.webhooks.spawn_deploy_worker", capture_spawn)
    _seed_webhook(db_session_factory, project_id, seeded_user.id)
    payload, body = _pr_payload("opened", "aaaabbbbcccc", "feature")
    headers = _headers(payload, "pull_request", "pr-retry-same-id")
    url = f"/webhooks/github/{project_id}"

    assert api_client.post(url, content=body, headers=headers).json() == {
        "status": "failed"
    }

    async def delivery_count() -> int:
        async with db_session_factory() as session:
            return len((await session.execute(
                select(GitHubWebhookDelivery).where(
                    GitHubWebhookDelivery.delivery_id == "pr-retry-same-id"
                )
            )).scalars().all())

    assert asyncio.run(delivery_count()) == 0

    state["fail"] = False
    assert api_client.post(url, content=body, headers=headers).json() == {
        "status": "received"
    }
    assert len(captured) == 1


def test_preview_quota_gate_fails_row_without_spawning(
    api_client, db_session_factory, seeded_user, monkeypatch
) -> None:
    project_id = uuid.uuid4()
    captured: list[object] = []

    async def fake_token(session, project_id) -> str:
        return "inst-token-xyz"

    async def capture_spawn(registry, job_id, worker, *worker_args) -> None:
        captured.append(worker_args)

    async def over_quota(*args, **kwargs) -> None:
        raise TeamComputeQuotaExceededError(
            "Team compute quota exceeded for running containers"
        )

    monkeypatch.setattr("app.api.routes.webhooks.installation_token", fake_token)
    monkeypatch.setattr("app.api.routes.webhooks.spawn_deploy_worker", capture_spawn)
    monkeypatch.setattr(
        "app.api.routes.webhooks.enforce_team_compute_capacity", over_quota
    )
    _seed_webhook(db_session_factory, project_id, seeded_user.id)
    payload, body = _pr_payload("opened", "ddddeeeeffff", "feature")
    delivery_id = "pr-over-quota"
    assert api_client.post(
        f"/webhooks/github/{project_id}",
        content=body,
        headers=_headers(payload, "pull_request", delivery_id),
    ).json() == {"status": "failed"}
    assert captured == []

    async def get_rows() -> tuple[GitHubWebhookDelivery, PreviewDeploy]:
        async with db_session_factory() as session:
            delivery = (
                await session.execute(
                    select(GitHubWebhookDelivery).where(
                        GitHubWebhookDelivery.delivery_id == delivery_id
                    )
                )
            ).scalar_one()
            preview = (
                await session.execute(
                    select(PreviewDeploy).where(
                        PreviewDeploy.project_id == project_id,
                        PreviewDeploy.pr_number == 21,
                    )
                )
            ).scalar_one()
            return delivery, preview

    delivery, preview = asyncio.run(get_rows())
    assert "quota" in (delivery.error or "").lower()
    assert preview.status == "failed"
