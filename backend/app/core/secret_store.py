from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SecretNotFoundError, SecretVersionNotFoundError
from app.core.security.secrets import decrypt_secret, encrypt_secret
from app.db.models import Secret, SecretVersion

SECRET_REF_PATTERN = re.compile(r"^secret://([A-Za-z0-9_.-]+)(?:@(\d+|latest))?$")


def parse_secret_reference(value: str) -> tuple[str, str] | None:
    match = SECRET_REF_PATTERN.match(value)
    if match is None:
        return None
    return match.group(1), match.group(2) or "latest"


async def create_secret(
    session: AsyncSession, *, owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None, name: str, value: str,
) -> Secret:
    secret = Secret(owner_user_id=owner_user_id, project_id=project_id, name=name)
    session.add(secret)
    await session.flush()
    session.add(SecretVersion(secret_id=secret.id, version=1, value_encrypted=encrypt_secret(value)))
    await session.commit()
    return secret


async def set_secret_value(session: AsyncSession, secret: Secret, value: str) -> SecretVersion:
    latest = (await session.execute(
        select(func.max(SecretVersion.version)).where(SecretVersion.secret_id == secret.id)
    )).scalar() or 0
    version = SecretVersion(
        secret_id=secret.id, version=latest + 1, value_encrypted=encrypt_secret(value),
    )
    session.add(version)
    secret.updated_at = datetime.now(UTC)
    await session.commit()
    return version


async def resolve_secret_reference(
    session: AsyncSession, *, owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None, name: str, version: str,
) -> str:
    query = select(Secret).where(Secret.name == name)
    query = query.where(Secret.project_id == project_id) if project_id is not None else query.where(Secret.owner_user_id == owner_user_id)
    secret = (await session.execute(query)).scalar_one_or_none()
    if secret is None:
        raise SecretNotFoundError(f"Secret {name!r} was not found")
    if version == "latest":
        row = (await session.execute(
            select(SecretVersion).where(SecretVersion.secret_id == secret.id).order_by(SecretVersion.version.desc()).limit(1)
        )).scalar_one_or_none()
    else:
        row = (await session.execute(
            select(SecretVersion).where(SecretVersion.secret_id == secret.id, SecretVersion.version == int(version))
        )).scalar_one_or_none()
    if row is None:
        raise SecretVersionNotFoundError(f"Secret {name!r} has no version {version}")
    return decrypt_secret(row.value_encrypted)
