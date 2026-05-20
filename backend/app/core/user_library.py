"""Per-user saved image references and Dockerfile templates (PostgreSQL)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DockerfileTemplateNotFoundError,
    DuplicateDockerfileNameError,
    DuplicateSavedImageError,
    SavedImageNotFoundError,
)
from app.db.models import Dockerfile, Image


def _normalize_ref(ref: str) -> str:
    trimmed = ref.strip()
    if not trimmed:
        raise ValueError("Image reference cannot be empty.")
    return trimmed


def _normalize_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Dockerfile name cannot be empty.")
    return trimmed


def _normalize_contents(contents: str) -> str:
    if not contents.strip():
        raise ValueError("Dockerfile contents cannot be empty.")
    return contents


async def list_saved_images(
    session: AsyncSession, owner_id: uuid.UUID
) -> list[Image]:
    result = await session.scalars(
        select(Image)
        .where(Image.owner_id == owner_id)
        .order_by(Image.created_at.desc())
    )
    return list(result.all())


async def get_saved_image(
    session: AsyncSession, owner_id: uuid.UUID, image_id: uuid.UUID
) -> Image:
    row = await session.scalar(
        select(Image).where(Image.id == image_id, Image.owner_id == owner_id)
    )
    if row is None:
        raise SavedImageNotFoundError(str(image_id))
    return row


async def create_saved_image(
    session: AsyncSession, owner_id: uuid.UUID, ref: str
) -> Image:
    normalized_ref = _normalize_ref(ref)
    row = Image(owner_id=owner_id, ref=normalized_ref)
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateSavedImageError(normalized_ref) from exc
    await session.refresh(row)
    return row


async def update_saved_image(
    session: AsyncSession,
    owner_id: uuid.UUID,
    image_id: uuid.UUID,
    *,
    ref: str,
) -> Image:
    row = await get_saved_image(session, owner_id, image_id)
    normalized_ref = _normalize_ref(ref)
    row.ref = normalized_ref
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateSavedImageError(normalized_ref) from exc
    await session.refresh(row)
    return row


async def delete_saved_image(
    session: AsyncSession, owner_id: uuid.UUID, image_id: uuid.UUID
) -> None:
    row = await get_saved_image(session, owner_id, image_id)
    await session.delete(row)
    await session.commit()


async def list_dockerfile_templates(
    session: AsyncSession, owner_id: uuid.UUID
) -> list[Dockerfile]:
    result = await session.scalars(
        select(Dockerfile)
        .where(Dockerfile.owner_id == owner_id)
        .order_by(Dockerfile.name.asc())
    )
    return list(result.all())


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
