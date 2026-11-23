"""Signed GitHub webhook receiver and GitHub App / webhook configuration APIs."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    get_current_user,
    get_db,
    get_db_session_factory,
    get_deploy_jobs,
    get_image_builder,
    get_orchestrator,
    get_traffic_router,
    require_admin,
)
from app.api.routes.containers import _run_container_deploy_worker
from app.api.routes.deploys import spawn_deploy_worker
from app.api.schemas import (
    GitHubAppConfigGet,
    GitHubAppConfigSet,
    GitHubWebhookConfigGet,
    GitHubWebhookConfigSet,
    GitHubWebhookDeliveryEntry,
    RunFromSourceRequest,
)
from app.core.auth.enums import UserRole
from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.deploy.jobs import DeployJobRegistry
from app.core.exceptions import (
    GitHubAppNotConfiguredError,
    TeamComputeQuotaExceededError,
    TeamStorageQuotaExceededError,
    WebhookSignatureError,
)
from app.core.github_app import installation_token, verify_github_signature
from app.core.previews import preview_deploy_config, teardown_preview
from app.core.projects.repository import require_owner
from app.core.quotas import (
    enforce_team_compute_capacity,
    enforce_team_storage_capacity,
)
from app.core.security.secrets import decrypt_secret, encrypt_secret
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import (
    GitHubAppInstall,
    GitHubWebhookConfig,
    GitHubWebhookDelivery,
    PreviewDeploy,
    User,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhooks/github/{project_id}", response_model=None)
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
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
) -> dict[str, str] | JSONResponse:
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

    raw_ref = str(body.get("ref") or "")
    if event == "push" and not raw_ref.startswith("refs/heads/"):
        return {"status": "ignored"}
    branch = raw_ref.removeprefix("refs/heads/")
    if event != "pull_request" and config.branch_filters and branch not in config.branch_filters:
        return {"status": "ignored"}

    repo_full_name = body["repository"]["full_name"]
    pull_request = body.get("pull_request") or {}
    pr_number = pull_request.get("number") if isinstance(pull_request.get("number"), int) else None
    is_fork = bool(((pull_request.get("head") or {}).get("repo") or {}).get("fork", False))
    action = body.get("action")
    preview_action = (
        event == "pull_request" and config.preview_enabled and pr_number is not None
        and action in {"opened", "synchronize", "reopened"}
    )
    push_action = event == "push" and config.enabled

    # Mint before recording the delivery: a transient failure must not leave a
    # committed delivery that dedups away GitHub's retry.
    token: str | None = None
    token_error: Exception | None = None
    if preview_action or push_action:
        try:
            token = await installation_token(session, project_id)
        except Exception as exc:
            token_error = exc
            logger.warning("Installation token unavailable for %s: %s", delivery_id, exc)
            if not isinstance(exc, GitHubAppNotConfiguredError):
                await _fail_existing_preview(
                    session, project_id, repo_full_name, pr_number, exc
                )
                # No delivery row exists yet: a 5xx lets GitHub auto-redeliver
                # without a committed delivery deduping the retry away.
                return JSONResponse(
                    status_code=503,
                    content={"status": "failed", "detail": f"GitHub token unavailable: {exc}"},
                )

    delivery = GitHubWebhookDelivery(
        delivery_id=delivery_id,
        project_id=project_id,
        repo_full_name=repo_full_name,
        event=event,
        action=action,
        branch=branch,
        pr_number=pr_number,
        is_fork=is_fork,
        status="failed" if token_error is not None else "received",
        error=str(token_error) if token_error is not None else None,
    )
    session.add(delivery)
    # The unique delivery_id constraint backstops the check above: a racing
    # duplicate loses the insert, so report it as a duplicate instead of 500.
    try:
        await session.commit()
    except IntegrityError:
        return {"status": "duplicate"}

    if preview_action:
        assert pr_number is not None
        if not await _enqueue_preview(
            session, background_tasks, registry, session_factory,
            orchestrator, traffic_router, image_builder, config, project_id,
            repo_full_name, pr_number, pull_request, delivery, token, token_error,
        ):
            return {"status": "failed"}
    elif event == "pull_request" and config.preview_enabled and pr_number is not None and action == "closed":
        await _teardown_preview_row(
            session, project_id, repo_full_name, pr_number,
            orchestrator, traffic_router,
        )
    elif push_action:
        if not await _enqueue_push_deploy(
            session, background_tasks, registry, session_factory,
            orchestrator, traffic_router, image_builder, config, project_id,
            repo_full_name, body, delivery, token, token_error,
        ):
            return {"status": "failed"}
    return {"status": "received"}


async def _fail_existing_preview(
    session: AsyncSession, project_id: uuid.UUID, repo_full_name: str,
    pr_number: int | None, error: Exception,
) -> None:
    """Best-effort status update for a preview that already exists on a transient failure."""
    if pr_number is None:
        return
    row = (
        await session.execute(
            select(PreviewDeploy).where(
                PreviewDeploy.project_id == project_id,
                PreviewDeploy.repo_full_name == repo_full_name,
                PreviewDeploy.pr_number == pr_number,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        row.status = "failed"
        await session.commit()


async def _enqueue_preview(
    session: AsyncSession,
    background_tasks: BackgroundTasks,
    registry: DeployJobRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    image_builder: DefaultImageBuilder,
    config: GitHubWebhookConfig,
    project_id: uuid.UUID,
    repo_full_name: str,
    pr_number: int,
    pull_request: dict,
    delivery: GitHubWebhookDelivery,
    token: str | None,
    token_error: Exception | None,
) -> bool:
    """Upsert the preview row and deploy the PR head through the source worker."""
    head = pull_request.get("head") or {}
    head_sha = str(head.get("sha") or "")
    head_ref = str(head.get("ref") or head_sha)
    clone_url = str((head.get("repo") or {}).get("clone_url") or "")
    if not clone_url or config.created_by_user_id is None:
        return True

    preview_config = preview_deploy_config(
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        head_sha=head_sha,
        image=clone_url,
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
        await teardown_preview(session, row, orchestrator, traffic_router)
        row.head_sha = head_sha
        row.expires_at = expires_at
        row.status = "pending"
        row.closed_at = None
        row.container_id = None
        row.container_name = None
        row.route_host = None
        row.public_url = None

    if token_error is not None:
        row.status = "failed"
        delivery.error = str(token_error)
        await session.commit()
        return False

    try:
        await enforce_team_compute_capacity(session, orchestrator, project_id)
    except TeamComputeQuotaExceededError as exc:
        logger.warning(
            "Preview quota gate rejected PR %s #%s: %s", repo_full_name, pr_number, exc
        )
        row.status = "failed"
        delivery.status = "failed"
        delivery.error = str(exc)
        await session.commit()
        return False
    await session.commit()
    assert token is not None

    run_body = RunFromSourceRequest(
        source_kind="git",
        git_url=clone_url,
        git_branch=head_ref,
        container_name=preview_config.name,
        container_port=80,
        public_route=True,
        env_vars=preview_config.env_vars,
        cpu_limit=preview_config.cpu_limit,
        memory_limit=preview_config.memory_limit,
        project_id=project_id,
    )
    job = await registry.create(
        kind="container",
        project_id=project_id,
        user_id=config.created_by_user_id,
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
        run_body,
        project_id,
        [],
        config.created_by_user_id,
        orchestrator,
        traffic_router,
        image_builder,
        token,
        "pr-",
        row.id,
    )
    return True


async def _run_preview_worker(
    registry: DeployJobRegistry,
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    body: RunFromSourceRequest,
    project_id: uuid.UUID,
    resolved_volumes: list,
    user_id: uuid.UUID,
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    image_builder: DefaultImageBuilder,
    access_token: str,
    route_label_prefix: str,
    preview_id: uuid.UUID,
) -> None:
    """Run the shared source worker, then mirror its outcome onto the preview row."""
    await _run_container_deploy_worker(
        registry, job_id, session_factory, body, project_id, resolved_volumes,
        user_id, orchestrator, traffic_router, image_builder,
        access_token, route_label_prefix,
    )
    job = await registry.get(job_id)
    async with session_factory() as session:
        row = await session.get(PreviewDeploy, preview_id)
        if row is None:
            return
        if job is not None and job.status == "succeeded":
            result = job.result or {}
            container = result.get("container") or {}
            row.container_id = container.get("id")
            row.container_name = container.get("name")
            row.public_url = result.get("public_url")
            row.status = "deployed"
        else:
            row.status = "failed"
        await session.commit()


async def _enqueue_push_deploy(
    session: AsyncSession,
    background_tasks: BackgroundTasks,
    registry: DeployJobRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    image_builder: DefaultImageBuilder,
    config: GitHubWebhookConfig,
    project_id: uuid.UUID,
    repo_full_name: str,
    body: dict,
    delivery: GitHubWebhookDelivery,
    token: str | None,
    token_error: Exception | None,
) -> bool:
    """Enqueue a production deploy of the pushed ref through the source worker."""
    clone_url = str((body.get("repository") or {}).get("clone_url") or "")
    head_sha = str(body.get("after") or "")
    if not clone_url or config.created_by_user_id is None:
        return True
    if token_error is not None:
        delivery.status = "failed"
        delivery.error = str(token_error)
        await session.commit()
        return False

    try:
        await enforce_team_compute_capacity(session, orchestrator, project_id)
        await enforce_team_storage_capacity(session, orchestrator, project_id)
    except (TeamComputeQuotaExceededError, TeamStorageQuotaExceededError) as exc:
        logger.warning("Push quota gate rejected %s: %s", repo_full_name, exc)
        delivery.status = "failed"
        delivery.error = str(exc)
        await session.commit()
        return False

    run_body = RunFromSourceRequest(
        source_kind="git",
        git_url=clone_url,
        git_branch=head_sha,
        container_port=80,
        env_vars={},
        project_id=project_id,
    )
    job = await registry.create(
        kind="container",
        project_id=project_id,
        user_id=config.created_by_user_id,
        name=repo_full_name,
        source_label=clone_url,
    )
    background_tasks.add_task(
        spawn_deploy_worker,
        registry,
        job.job_id,
        _run_push_deploy_worker,
        registry,
        job.job_id,
        session_factory,
        run_body,
        project_id,
        [],
        config.created_by_user_id,
        orchestrator,
        traffic_router,
        image_builder,
        token,
        None,
        delivery.id,
    )
    return True


async def _run_push_deploy_worker(
    registry: DeployJobRegistry,
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    body: RunFromSourceRequest,
    project_id: uuid.UUID,
    resolved_volumes: list,
    user_id: uuid.UUID,
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    image_builder: DefaultImageBuilder,
    access_token: str,
    route_label_prefix: str | None,
    delivery_id: uuid.UUID,
) -> None:
    """Deploy the pushed source, then mirror the job outcome onto the delivery."""
    await _run_container_deploy_worker(
        registry, job_id, session_factory, body, project_id, resolved_volumes,
        user_id, orchestrator, traffic_router, image_builder,
        access_token, route_label_prefix,
    )
    job = await registry.get(job_id)
    async with session_factory() as session:
        delivery = await session.get(GitHubWebhookDelivery, delivery_id)
        if delivery is None:
            return
        if job is not None and job.status == "succeeded":
            delivery.status = "deployed"
        else:
            delivery.status = "failed"
            if job is not None and job.error:
                delivery.error = str(job.error)
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
