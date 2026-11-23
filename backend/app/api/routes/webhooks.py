"""Signed GitHub webhook receiver and GitHub App / webhook configuration APIs."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    get_current_user,
    get_db,
    get_db_session_factory,
    get_deploy_jobs,
    get_orchestrator,
    get_traffic_router,
    require_admin,
)
from app.api.route_wiring import (
    backend_port_for_route,
    register_route_for_deployed_container,
)
from app.api.routes.deploys import spawn_deploy_worker
from app.api.schemas import (
    GitHubAppConfigGet,
    GitHubAppConfigSet,
    GitHubWebhookConfigGet,
    GitHubWebhookConfigSet,
    GitHubWebhookDeliveryEntry,
)
from app.core.auth.enums import UserRole
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.deploy.jobs import DeployJobRegistry, classify_deploy_error
from app.core.deploy.secret_resolution import runtime_config_with_secrets
from app.core.exceptions import GitHubAppNotConfiguredError, WebhookSignatureError
from app.core.github_app import verify_github_signature
from app.core.models import DeployConfig
from app.core.previews import preview_deploy_config, teardown_preview
from app.core.projects.repository import require_owner
from app.core.security.secrets import decrypt_secret, encrypt_secret
from app.core.traffic.public_route_host import (
    apply_public_route_to_deploy_config,
    build_public_url,
    read_public_route_settings,
)
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import (
    GitHubAppInstall,
    GitHubWebhookConfig,
    GitHubWebhookDelivery,
    PreviewDeploy,
    User,
)

router = APIRouter()


@router.post("/webhooks/github/{project_id}")
async def github_webhook(
    project_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db)],
    registry: Annotated[DeployJobRegistry, Depends(get_deploy_jobs)],
    session_factory: Annotated[
        async_sessionmaker[AsyncSession], Depends(get_db_session_factory)
    ],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
) -> dict[str, str]:
    """Verify the HMAC, record the delivery and accept configured push / PR events."""
    payload = await request.body()
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    signature = request.headers.get("X-Hub-Signature-256")
    event = request.headers.get("X-GitHub-Event", "")
    install = (await session.execute(select(GitHubAppInstall))).scalar_one_or_none()
    if install is None:
        raise GitHubAppNotConfiguredError("GitHub App is not configured")
    if not verify_github_signature(
        payload, decrypt_secret(install.webhook_secret_encrypted), signature
    ):
        raise WebhookSignatureError("Invalid webhook signature")

    existing = (
        await session.execute(
            select(GitHubWebhookDelivery).where(
                GitHubWebhookDelivery.delivery_id == delivery_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"status": "duplicate"}

    body = json.loads(payload)
    config = (
        await session.execute(
            select(GitHubWebhookConfig).where(
                GitHubWebhookConfig.project_id == project_id,
                GitHubWebhookConfig.repo_full_name == body["repository"]["full_name"],
                GitHubWebhookConfig.enabled.is_(True),
            )
        )
    ).scalar_one_or_none()
    if config is None:
        return {"status": "ignored"}

    branch = body.get("ref", "").removeprefix("refs/heads/")
    if event != "pull_request" and config.branch_filters and branch not in config.branch_filters:
        return {"status": "ignored"}

    pull_request = body.get("pull_request") or {}
    pr_number = pull_request.get("number") if isinstance(pull_request.get("number"), int) else None
    is_fork = bool(((pull_request.get("head") or {}).get("repo") or {}).get("fork", False))

    delivery = GitHubWebhookDelivery(
        delivery_id=delivery_id,
        project_id=project_id,
        repo_full_name=body["repository"]["full_name"],
        event=event,
        action=body.get("action"),
        branch=branch,
        pr_number=pr_number,
        is_fork=is_fork,
        status="received",
    )
    session.add(delivery)
    # The unique delivery_id constraint backstops the check above: a racing
    # duplicate loses the insert, so report it as a duplicate instead of 500.
    try:
        await session.commit()
    except IntegrityError:
        return {"status": "duplicate"}

    if event == "pull_request" and config.preview_enabled and pr_number is not None:
        action = body.get("action")
        repo_full_name = body["repository"]["full_name"]
        if action in {"opened", "synchronize", "reopened"}:
            await _enqueue_preview(
                session, background_tasks, registry, session_factory,
                orchestrator, traffic_router, config, project_id, repo_full_name,
                pr_number, pull_request,
            )
        elif action == "closed":
            await _teardown_preview_row(
                session, project_id, repo_full_name, pr_number,
                orchestrator, traffic_router,
            )
    return {"status": "received"}


async def _enqueue_preview(
    session: AsyncSession,
    background_tasks: BackgroundTasks,
    registry: DeployJobRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    config: GitHubWebhookConfig,
    project_id: uuid.UUID,
    repo_full_name: str,
    pr_number: int,
    pull_request: dict,
) -> None:
    """Upsert the preview row and spawn its detached deploy worker."""
    head_sha = str((pull_request.get("head") or {}).get("sha") or "")
    preview_config = preview_deploy_config(
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        head_sha=head_sha,
        image=os.environ.get("VELA_PREVIEW_IMAGE", "nginx:latest"),
        env_vars={},
        ttl_seconds=config.preview_ttl_seconds,
    )
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=config.preview_ttl_seconds)
    row = (
        await session.execute(
            select(PreviewDeploy).where(
                PreviewDeploy.project_id == project_id,
                PreviewDeploy.repo_full_name == repo_full_name,
                PreviewDeploy.pr_number == pr_number,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = PreviewDeploy(
            project_id=project_id, repo_full_name=repo_full_name,
            pr_number=pr_number, head_sha=head_sha, expires_at=expires_at,
            status="pending",
        )
        session.add(row)
    else:
        row.head_sha = head_sha
        row.expires_at = expires_at
        row.status = "pending"
        row.closed_at = None
    await session.commit()

    owner_user_id = config.created_by_user_id or row.id
    job = await registry.create(
        kind="container",
        project_id=project_id,
        user_id=owner_user_id,
        name=preview_config.name or f"pr-{pr_number}",
        source_label=repo_full_name,
    )
    background_tasks.add_task(
        spawn_deploy_worker,
        registry,
        job.job_id,
        _run_preview_worker,
        registry,
        job.job_id,
        session_factory,
        row.id,
        preview_config,
        owner_user_id,
        project_id,
        orchestrator,
        traffic_router,
    )


async def _run_preview_worker(
    registry: DeployJobRegistry,
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    preview_id: uuid.UUID,
    preview_config: DeployConfig,
    owner_user_id: uuid.UUID,
    project_id: uuid.UUID,
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
) -> None:
    """Deploy a preview with secrets disabled and a ``pr-`` route prefix."""
    try:
        async with session_factory() as session:
            config = await runtime_config_with_secrets(
                session, preview_config, owner_user_id=owner_user_id,
                project_id=project_id, allow_secrets=False,
            )
            config = await apply_public_route_to_deploy_config(
                config, traffic_router, label_prefix="pr-"
            )
            await registry.set_phase(job_id, "starting", config.image)
            info = await orchestrator.deploy(config)
            route_host = config.route_host or ""
            await register_route_for_deployed_container(
                traffic_router=traffic_router,
                container_info=info,
                route_host=route_host,
                path_prefix=config.route_path_prefix,
                backend_port=backend_port_for_route(config),
                tls_enabled=config.route_tls,
            )
            _, scheme, _ = read_public_route_settings()
            public_url = build_public_url(
                scheme=scheme, host=route_host, path_prefix=config.route_path_prefix
            )
            row = await session.get(PreviewDeploy, preview_id)
            if row is not None:
                row.container_id = info.id
                row.container_name = info.name
                row.route_host = route_host
                row.public_url = public_url
                row.status = "deployed"
                await session.commit()
            await registry.complete_success(job_id, {"public_url": public_url})
    except Exception as exc:
        await registry.complete_failure(job_id, classify_deploy_error(exc))
        async with session_factory() as session:
            row = await session.get(PreviewDeploy, preview_id)
            if row is not None:
                row.status = "failed"
                await session.commit()


async def _teardown_preview_row(
    session: AsyncSession,
    project_id: uuid.UUID,
    repo_full_name: str,
    pr_number: int,
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
) -> None:
    row = (
        await session.execute(
            select(PreviewDeploy).where(
                PreviewDeploy.project_id == project_id,
                PreviewDeploy.repo_full_name == repo_full_name,
                PreviewDeploy.pr_number == pr_number,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return
    await teardown_preview(session, row, orchestrator, traffic_router)
    await session.commit()


def _app_config(install: GitHubAppInstall | None) -> GitHubAppConfigGet:
    if install is None:
        return GitHubAppConfigGet(
            configured=False,
            app_id=None,
            slug=None,
            has_private_key=False,
            has_webhook_secret=False,
            connected_at=None,
        )
    return GitHubAppConfigGet(
        configured=True,
        app_id=install.app_id,
        slug=install.slug,
        has_private_key=bool(install.private_key_encrypted),
        has_webhook_secret=bool(install.webhook_secret_encrypted),
        connected_at=install.connected_at,
    )


@router.get("/api/settings/github-app", response_model=GitHubAppConfigGet)
async def get_github_app_config(
    _: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GitHubAppConfigGet:
    """Return GitHub App metadata; secrets are never included."""
    install = (await session.execute(select(GitHubAppInstall))).scalar_one_or_none()
    return _app_config(install)


@router.put("/api/settings/github-app", response_model=GitHubAppConfigGet)
async def put_github_app_config(
    body: GitHubAppConfigSet,
    _: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GitHubAppConfigGet:
    """Store the App credentials encrypted at rest and return metadata only."""
    install = (await session.execute(select(GitHubAppInstall))).scalar_one_or_none()
    if install is None:
        install = GitHubAppInstall(connected_at=datetime.now(UTC))
    install.app_id = body.app_id
    install.slug = body.slug
    install.private_key_encrypted = encrypt_secret(body.private_key)
    install.webhook_secret_encrypted = encrypt_secret(body.webhook_secret)
    session.add(install)
    result = _app_config(install)
    await session.commit()
    return result


def _project_config(
    project_id: uuid.UUID, row: GitHubWebhookConfig | None
) -> GitHubWebhookConfigGet:
    return GitHubWebhookConfigGet(
        project_id=project_id,
        repo_full_name=row.repo_full_name if row is not None else None,
        enabled=row.enabled if row is not None else False,
        branch_filters=list(row.branch_filters) if row is not None else [],
        preview_enabled=row.preview_enabled if row is not None else False,
        preview_ttl_seconds=row.preview_ttl_seconds if row is not None else 3600,
    )


async def _require_owner_or_admin(
    session: AsyncSession, project_id: uuid.UUID, user: User
) -> None:
    if user.role != UserRole.ADMIN:
        await require_owner(session, project_id=project_id, user_id=user.id)


@router.get(
    "/api/projects/{project_id}/github-webhook", response_model=GitHubWebhookConfigGet
)
async def get_project_webhook_config(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GitHubWebhookConfigGet:
    await _require_owner_or_admin(session, project_id, current_user)
    row = await session.get(GitHubWebhookConfig, project_id)
    return _project_config(project_id, row)


@router.put(
    "/api/projects/{project_id}/github-webhook", response_model=GitHubWebhookConfigGet
)
async def put_project_webhook_config(
    project_id: uuid.UUID,
    body: GitHubWebhookConfigSet,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GitHubWebhookConfigGet:
    await _require_owner_or_admin(session, project_id, current_user)
    row = await session.get(GitHubWebhookConfig, project_id)
    if row is None:
        row = GitHubWebhookConfig(project_id=project_id)
    row.repo_full_name = body.repo_full_name
    row.enabled = body.enabled
    row.branch_filters = list(body.branch_filters)
    row.preview_enabled = body.preview_enabled
    row.preview_ttl_seconds = body.preview_ttl_seconds
    row.created_by_user_id = current_user.id
    session.add(row)
    result = _project_config(project_id, row)
    await session.commit()
    return result


@router.get(
    "/api/projects/{project_id}/github-webhook/deliveries",
    response_model=list[GitHubWebhookDeliveryEntry],
)
async def get_project_webhook_deliveries(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[GitHubWebhookDeliveryEntry]:
    await _require_owner_or_admin(session, project_id, current_user)
    rows = (
        await session.execute(
            select(GitHubWebhookDelivery)
            .where(GitHubWebhookDelivery.project_id == project_id)
            .order_by(GitHubWebhookDelivery.received_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [GitHubWebhookDeliveryEntry.model_validate(row) for row in rows]
