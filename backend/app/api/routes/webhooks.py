"""Signed GitHub webhook receiver and GitHub App / webhook configuration APIs."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_deploy_jobs, require_admin
from app.api.schemas import (
    GitHubAppConfigGet,
    GitHubAppConfigSet,
    GitHubWebhookConfigGet,
    GitHubWebhookConfigSet,
    GitHubWebhookDeliveryEntry,
)
from app.core.auth.enums import UserRole
from app.core.deploy.jobs import DeployJobRegistry
from app.core.exceptions import GitHubAppNotConfiguredError, WebhookSignatureError
from app.core.github_app import verify_github_signature
from app.core.projects.repository import require_owner
from app.core.security.secrets import decrypt_secret, encrypt_secret
from app.db.models import (
    GitHubAppInstall,
    GitHubWebhookConfig,
    GitHubWebhookDelivery,
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
) -> dict[str, str]:
    """Verify the HMAC, record the delivery and accept configured push events."""
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
    if config.branch_filters and branch not in config.branch_filters:
        return {"status": "ignored"}

    delivery = GitHubWebhookDelivery(
        delivery_id=delivery_id,
        project_id=project_id,
        repo_full_name=body["repository"]["full_name"],
        event=event,
        action=body.get("action"),
        branch=branch,
        status="received",
    )
    session.add(delivery)
    await session.commit()
    return {"status": "received"}


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
