"""Resolve user-facing deploy source labels (e.g. Dockerfile template names)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import user_library
from app.core.exceptions import DockerfileTemplateNotFoundError


def source_ref_looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


async def resolve_deploy_source_label(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    source_kind: str,
    source_ref: str,
) -> str:
    """
    Return the label shown in UI lists (Builder template ``name``, image ref, Git URL).

    Legacy deployment rows stored the template UUID in ``source_ref``; resolve it here.
    """
    if source_kind != "dockerfile_template":
        return source_ref
    if not source_ref_looks_like_uuid(source_ref):
        return source_ref
    try:
        template = await user_library.get_dockerfile_template(
            session, owner_id, uuid.UUID(source_ref)
        )
    except DockerfileTemplateNotFoundError:
        return source_ref
    return template.name
