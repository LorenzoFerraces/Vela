"""Persist and compare deployment snapshots."""

from __future__ import annotations

import difflib
import json
import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ConfigFieldDiff,
    DeploymentDiffResponse,
    DeploymentEnvDiff,
    DeploymentRecordPublic,
)
from app.core.deploy.deploy_source_display import resolve_deploy_source_label
from app.core.models import DeployConfig
from app.core.security.secrets import decrypt_secret, encrypt_secret
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
    build_override: dict | None = None
    deploy_config: dict | None = None


_ENCRYPTED_PREFIX = "enc:"


def _encode_deploy_config(config: dict) -> str:
    """Encrypt the serialized config so user env secrets are not stored in plaintext."""
    ciphertext = encrypt_secret(json.dumps(config))
    return _ENCRYPTED_PREFIX + ciphertext.decode("ascii")


def _decode_deploy_config(raw: object) -> dict | None:
    """Decrypt a marked snapshot; accept legacy plaintext dicts unchanged."""
    if raw is None:
        return None
    if isinstance(raw, str) and raw.startswith(_ENCRYPTED_PREFIX):
        ciphertext = raw[len(_ENCRYPTED_PREFIX):].encode("ascii")
        return json.loads(decrypt_secret(ciphertext))
    if isinstance(raw, dict):
        return raw
    return None


async def record_deployment(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    snapshot: DeploymentSnapshot,
) -> DeploymentRecord:
    row = DeploymentRecord(
        user_id=user_id,
        project_id=project_id,
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
        build_override=snapshot.build_override,
        deploy_config=(
            _encode_deploy_config(snapshot.deploy_config)
            if snapshot.deploy_config is not None
            else None
        ),
        public_url=snapshot.public_url,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def load_deploy_config_snapshot(
    session: AsyncSession, container_id: str
) -> DeployConfig | None:
    """Return the full DeployConfig recorded for ``container_id``, or None."""
    result = await session.execute(
        select(DeploymentRecord.deploy_config)
        .where(DeploymentRecord.container_id == container_id)
        .order_by(DeploymentRecord.created_at.desc())
        .limit(1)
    )
    raw = result.scalar_one_or_none()
    decoded = _decode_deploy_config(raw)
    if decoded is None:
        return None
    return DeployConfig.model_validate(decoded)


MUTABLE_FIELDS = frozenset({
    "env_vars", "command", "labels", "health_check", "cpu_limit", "memory_limit",
    "route_host", "route_path_prefix", "route_tls", "public_route", "restart_policy",
})


def classify_update(update: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    """Split a config update into mutable fields and fields needing recreation."""
    mutable = {key: value for key, value in update.items() if key in MUTABLE_FIELDS}
    rejected = sorted(
        key for key, value in update.items()
        if key not in MUTABLE_FIELDS and key in DeployConfig.model_fields and value is not None
    )
    return mutable, rejected


def diff_config_fields(
    before: DeployConfig, after: DeployConfig
) -> dict[str, ConfigFieldDiff]:
    """Describe changed mutable fields without ever touching secret values."""
    return {
        field: ConfigFieldDiff(before=getattr(before, field), after=getattr(after, field))
        for field in sorted(MUTABLE_FIELDS)
        if getattr(before, field) != getattr(after, field)
    }


async def _to_public(
    session: AsyncSession,
    user_id: uuid.UUID,
    row: DeploymentRecord,
    author_email: str,
) -> DeploymentRecordPublic:
    source_ref = await resolve_deploy_source_label(
        session,
        user_id,
        source_kind=row.source_kind,
        source_ref=row.source_ref,
    )
    return DeploymentRecordPublic(
        id=row.id,
        user_id=row.user_id,
        project_id=row.project_id,
        author_email=author_email,
        container_id=row.container_id,
        container_name=row.container_name,
        source_kind=row.source_kind,  # type: ignore[arg-type]
        source_ref=source_ref,
        git_branch=row.git_branch,
        image_tag=row.image_tag,
        container_port=row.container_port,
        env_vars=row.env_vars or {},
        command=row.command,
        dockerfile_snapshot=row.dockerfile_snapshot,
        build_override=row.build_override,
        public_url=row.public_url,
        created_at=row.created_at,
    )


async def latest_source_by_container_ids(
    session: AsyncSession,
    user_id: uuid.UUID,
    container_ids: list[str],
    project_ids: Collection[uuid.UUID] | None = None,
) -> dict[str, tuple[str, str]]:
    """Most recent ``(source_kind, source_ref)`` per container id for history fallback."""
    if not container_ids:
        return {}
    if project_ids is None:
        from app.core.projects.repository import list_project_ids_for_user

        project_ids = await list_project_ids_for_user(session, user_id)
    result = await session.execute(
        select(DeploymentRecord)
        .where(
            DeploymentRecord.container_id.in_(container_ids),
            DeploymentRecord.project_id.in_(project_ids),
        )
        .order_by(DeploymentRecord.created_at.desc())
    )
    out: dict[str, tuple[str, str]] = {}
    for row in result.scalars():
        if row.container_id not in out:
            out[row.container_id] = (row.source_kind, row.source_ref)
    return out


async def list_deployments(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    container_name: str | None = None,
    limit: int = 50,
) -> list[DeploymentRecordPublic]:
    from app.core.projects.repository import list_project_ids_for_user

    project_ids = await list_project_ids_for_user(session, user_id)
    if not project_ids:
        return []
    bounded_limit = max(1, min(limit, 100))
    query = (
        select(DeploymentRecord, User.email)
        .join(User, User.id == DeploymentRecord.user_id)
        .where(DeploymentRecord.project_id.in_(project_ids))
        .order_by(DeploymentRecord.created_at.desc())
        .limit(bounded_limit)
    )
    trimmed_name = (container_name or "").strip()
    if trimmed_name:
        query = query.where(DeploymentRecord.container_name == trimmed_name)
    result = await session.execute(query)
    public_rows: list[DeploymentRecordPublic] = []
    for row, email in result.all():
        public_rows.append(await _to_public(session, user_id, row, email))
    return public_rows


async def get_deployment(
    session: AsyncSession,
    user_id: uuid.UUID,
    deployment_id: uuid.UUID,
) -> DeploymentRecordPublic | None:
    from app.core.projects.repository import list_project_ids_for_user

    project_ids = set(await list_project_ids_for_user(session, user_id))
    result = await session.execute(
        select(DeploymentRecord, User.email)
        .join(User, User.id == DeploymentRecord.user_id)
        .where(DeploymentRecord.id == deployment_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    deployment, email = row
    if deployment.project_id not in project_ids:
        return None
    return await _to_public(session, user_id, deployment, email)


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
    from app.core.projects.repository import list_project_ids_for_user

    project_ids = set(await list_project_ids_for_user(session, user_id))
    left = await session.get(DeploymentRecord, left_id)
    right = await session.get(DeploymentRecord, right_id)
    if left is None or right is None:
        return None
    if left.project_id not in project_ids or right.project_id not in project_ids:
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
