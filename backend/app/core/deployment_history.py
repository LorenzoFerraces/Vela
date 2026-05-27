"""Persist and compare deployment snapshots."""

from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DeploymentDiffResponse, DeploymentEnvDiff, DeploymentRecordPublic
from app.db.models import DeploymentRecord, User


@dataclass(frozen=True)
class DeploymentSnapshot:
    container_id: str
    container_name: str | None
    source_kind: str
    source_ref: str
    git_branch: str | None
    image_tag: str
    container_port: int
    env_vars: dict[str, str]
    command: list[str] | None
    dockerfile_snapshot: str | None
    public_url: str | None


async def record_deployment(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    snapshot: DeploymentSnapshot,
) -> DeploymentRecord:
    row = DeploymentRecord(
        user_id=user_id,
        container_id=snapshot.container_id,
        container_name=snapshot.container_name,
        source_kind=snapshot.source_kind,
        source_ref=snapshot.source_ref,
        git_branch=snapshot.git_branch,
        image_tag=snapshot.image_tag,
        container_port=snapshot.container_port,
        env_vars=dict(snapshot.env_vars),
        command=list(snapshot.command) if snapshot.command else None,
        dockerfile_snapshot=snapshot.dockerfile_snapshot,
        public_url=snapshot.public_url,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def _to_public(row: DeploymentRecord, author_email: str) -> DeploymentRecordPublic:
    return DeploymentRecordPublic(
        id=row.id,
        user_id=row.user_id,
        author_email=author_email,
        container_id=row.container_id,
        container_name=row.container_name,
        source_kind=row.source_kind,  # type: ignore[arg-type]
        source_ref=row.source_ref,
        git_branch=row.git_branch,
        image_tag=row.image_tag,
        container_port=row.container_port,
        env_vars=row.env_vars or {},
        command=row.command,
        dockerfile_snapshot=row.dockerfile_snapshot,
        public_url=row.public_url,
        created_at=row.created_at,
    )


async def list_deployments(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    container_name: str | None = None,
    limit: int = 50,
) -> list[DeploymentRecordPublic]:
    bounded_limit = max(1, min(limit, 100))
    query = (
        select(DeploymentRecord, User.email)
        .join(User, User.id == DeploymentRecord.user_id)
        .where(DeploymentRecord.user_id == user_id)
        .order_by(DeploymentRecord.created_at.desc())
        .limit(bounded_limit)
    )
    trimmed_name = (container_name or "").strip()
    if trimmed_name:
        query = query.where(DeploymentRecord.container_name == trimmed_name)
    result = await session.execute(query)
    return [
        _to_public(row, email)
        for row, email in result.all()
    ]


async def get_deployment(
    session: AsyncSession,
    user_id: uuid.UUID,
    deployment_id: uuid.UUID,
) -> DeploymentRecordPublic | None:
    result = await session.execute(
        select(DeploymentRecord, User.email)
        .join(User, User.id == DeploymentRecord.user_id)
        .where(
            DeploymentRecord.id == deployment_id,
            DeploymentRecord.user_id == user_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        return None
    deployment, email = row
    return _to_public(deployment, email)


def _diff_env(
    left_env: dict[str, str],
    right_env: dict[str, str],
) -> DeploymentEnvDiff:
    left_keys = set(left_env)
    right_keys = set(right_env)
    added = {key: right_env[key] for key in sorted(right_keys - left_keys)}
    removed = {key: left_env[key] for key in sorted(left_keys - right_keys)}
    changed = {
        key: {"before": left_env[key], "after": right_env[key]}
        for key in sorted(left_keys & right_keys)
        if left_env[key] != right_env[key]
    }
    return DeploymentEnvDiff(added=added, removed=removed, changed=changed)


def _diff_dockerfile(
    left_text: str | None,
    right_text: str | None,
) -> list[str]:
    left_lines = (left_text or "").splitlines(keepends=True)
    right_lines = (right_text or "").splitlines(keepends=True)
    return list(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile="left",
            tofile="right",
            lineterm="",
        )
    )


async def diff_deployments(
    session: AsyncSession,
    user_id: uuid.UUID,
    left_id: uuid.UUID,
    right_id: uuid.UUID,
) -> DeploymentDiffResponse | None:
    left = await session.get(DeploymentRecord, left_id)
    right = await session.get(DeploymentRecord, right_id)
    if left is None or right is None:
        return None
    if left.user_id != user_id or right.user_id != user_id:
        return None
    return DeploymentDiffResponse(
        left_id=left_id,
        right_id=right_id,
        env=_diff_env(left.env_vars or {}, right.env_vars or {}),
        dockerfile_diff=_diff_dockerfile(
            left.dockerfile_snapshot,
            right.dockerfile_snapshot,
        ),
    )
