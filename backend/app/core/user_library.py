"""Per-user Dockerfile templates (PostgreSQL)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DockerfileTemplateNotFoundError,
    DuplicateDockerfileNameError,
)
from app.db.models import Dockerfile


def _normalize_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Dockerfile name cannot be empty.")
    return trimmed


def _normalize_contents(contents: str) -> str:
    if not contents.strip():
        raise ValueError("Dockerfile contents cannot be empty.")
    return contents


async def list_dockerfile_templates(
    session: AsyncSession, owner_id: uuid.UUID
) -> list[Dockerfile]:
    result = await session.scalars(
        select(Dockerfile)
        .where(Dockerfile.owner_id == owner_id)
        .order_by(Dockerfile.name.asc())
    )
    return list(result.all())


async def list_dockerfile_templates_matching_name(
    session: AsyncSession,
    owner_id: uuid.UUID,
    query: str,
    *,
    limit: int = 20,
) -> list[Dockerfile]:
    """Return templates whose name contains ``query`` (case-insensitive)."""
    trimmed = query.strip()
    rows = await list_dockerfile_templates(session, owner_id)
    if not trimmed:
        return rows[:limit]
    needle = trimmed.casefold()
    matched = [row for row in rows if needle in row.name.casefold()]
    return matched[:limit]


async def get_dockerfile_template(
    session: AsyncSession, owner_id: uuid.UUID, template_id: uuid.UUID
) -> Dockerfile:
    row = await session.scalar(
        select(Dockerfile).where(
            Dockerfile.id == template_id, Dockerfile.owner_id == owner_id
        )
    )
    if row is None:
        raise DockerfileTemplateNotFoundError(str(template_id))
    return row


async def create_dockerfile_template(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    name: str,
    contents: str,
) -> Dockerfile:
    normalized_name = _normalize_name(name)
    normalized_contents = _normalize_contents(contents)
    row = Dockerfile(
        owner_id=owner_id,
        name=normalized_name,
        contents=normalized_contents,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateDockerfileNameError(normalized_name) from exc
    await session.refresh(row)
    return row


async def update_dockerfile_template(
    session: AsyncSession,
    owner_id: uuid.UUID,
    template_id: uuid.UUID,
    *,
    name: str | None = None,
    contents: str | None = None,
) -> Dockerfile:
    row = await get_dockerfile_template(session, owner_id, template_id)
    if name is not None:
        row.name = _normalize_name(name)
    if contents is not None:
        row.contents = _normalize_contents(contents)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateDockerfileNameError(row.name) from exc
    await session.refresh(row)
    return row


async def delete_dockerfile_template(
    session: AsyncSession, owner_id: uuid.UUID, template_id: uuid.UUID
) -> None:
    row = await get_dockerfile_template(session, owner_id, template_id)
    await session.delete(row)
    await session.commit()
