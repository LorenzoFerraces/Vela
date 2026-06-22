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
    """
    Trim leading and trailing whitespace from a Dockerfile name and validate it is not empty.

    Parameters:
        name (str): The input Dockerfile name, possibly containing surrounding whitespace.

    Returns:
        normalized_name (str): The name with leading and trailing whitespace removed.

    Raises:
        ValueError: If the trimmed name is empty.
    """
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Dockerfile name cannot be empty.")
    return trimmed


def _normalize_contents(contents: str) -> str:
    """
    Validate that Dockerfile contents are not empty or only whitespace.

    Parameters:
        contents (str): The Dockerfile text to validate.

    Returns:
        contents (str): The original `contents` string unchanged.

    Raises:
        ValueError: If `contents` is empty or contains only whitespace.
    """
    if not contents.strip():
        raise ValueError("Dockerfile contents cannot be empty.")
    return contents


async def list_dockerfile_templates(
    session: AsyncSession, owner_id: uuid.UUID
) -> list[Dockerfile]:
    """
    List all Dockerfile templates belonging to a specific owner, ordered by template name.

    Parameters:
        owner_id (uuid.UUID): The owner identifier to scope the query.

    Returns:
        templates (list[Dockerfile]): A list of Dockerfile records owned by `owner_id`, ordered ascending by `name`.
    """
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
    """
    List an owner's Dockerfile templates whose names contain the given query string, case-insensitively.

    The `query` is trimmed of surrounding whitespace before matching; an empty or whitespace-only query returns the owner's templates ordered by name up to `limit`. Matching is performed case-insensitively against template names.

    Parameters:
        query (str): Substring to search for within template names; leading/trailing whitespace is ignored.
        limit (int): Maximum number of templates to return.

    Returns:
        list[Dockerfile]: Templates belonging to `owner_id` whose names contain the trimmed `query`, limited to `limit` entries.
    """
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
    """
    Retrieve a Dockerfile template scoped to the given owner and template identifiers.

    Parameters:
        owner_id (uuid.UUID): UUID of the template owner.
        template_id (uuid.UUID): UUID of the Dockerfile template to fetch.

    Returns:
        Dockerfile: The matching Dockerfile instance.

    Raises:
        DockerfileTemplateNotFoundError: If no template with the given `template_id` exists for `owner_id`.
    """
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
    """
    Create a new Dockerfile template owned by the specified user.

    Parameters:
        session (AsyncSession): Database session used to persist the template.
        owner_id (uuid.UUID): ID of the owner who will own the created template.
        name (str): Template name; leading and trailing whitespace will be removed and empty names are rejected.
        contents (str): Template contents; blank or whitespace-only contents are rejected.

    Returns:
        Dockerfile: The persisted Dockerfile instance (including generated identifiers and persisted fields).

    Raises:
        DuplicateDockerfileNameError: If a template with the same name already exists for the owner.
    """
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
    """
    Update fields of a Dockerfile template owned by the given user and return the updated record.

    Parameters:
        session: AsyncSession used to load and persist the template.
        owner_id: UUID of the template owner used to scope access.
        template_id: UUID of the template to update.
        name: New template name; if provided, it is normalized and validated.
        contents: New template contents; if provided, it is validated.

    Returns:
        The updated Dockerfile instance with persisted changes.

    Raises:
        DockerfileTemplateNotFoundError: If no template with the given id exists for the owner.
        DuplicateDockerfileNameError: If the new name conflicts with another template for the same owner.
    """
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
    """
    Delete the Dockerfile template identified by `template_id` that belongs to `owner_id`.

    Parameters:
        owner_id (uuid.UUID): ID of the owner whose template should be deleted.
        template_id (uuid.UUID): ID of the Dockerfile template to remove.

    Raises:
        DockerfileTemplateNotFoundError: If no template with `template_id` exists for `owner_id`.
    """
    row = await get_dockerfile_template(session, owner_id, template_id)
    await session.delete(row)
    await session.commit()
