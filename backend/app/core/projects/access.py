"""Container access checks scoped by project membership."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.docker_orchestrator import VELA_OWNER_LABEL, VELA_PROJECT_LABEL
from app.core.exceptions import ContainerNotFoundError, ProjectAccessDeniedError
from app.core.models import ContainerInfo
from app.core.projects.enums import ProjectRole, can_read, can_write
from app.core.projects.repository import get_membership, get_personal_project_id
from app.core.containers.orchestrator import ContainerOrchestrator
from app.db.models import User


async def resolve_container_project_id(
    session: AsyncSession,
    info: ContainerInfo,
) -> uuid.UUID | None:
    label_value = info.labels.get(VELA_PROJECT_LABEL)
    if label_value:
        try:
            return uuid.UUID(label_value)
        except ValueError:
            return None
    owner_label = info.labels.get(VELA_OWNER_LABEL)
    if not owner_label:
        return None
    try:
        owner_id = uuid.UUID(owner_label)
    except ValueError:
        return None
    owner = await session.get(User, owner_id)
    if owner is None:
        return None
    return await get_personal_project_id(session, owner)


async def membership_role_for_container(
    session: AsyncSession,
    user_id: uuid.UUID,
    info: ContainerInfo,
) -> ProjectRole | None:
    project_id = await resolve_container_project_id(session, info)
    if project_id is None:
        return None
    membership = await get_membership(
        session, project_id=project_id, user_id=user_id
    )
    if membership is None:
        return None
    return ProjectRole(membership.role)


async def require_container_access(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    user: User,
    container_id: str,
    *,
    action: Literal["read", "write"],
) -> ContainerInfo:
    info = await orchestrator.get(container_id)
    role = await membership_role_for_container(session, user.id, info)
    if role is None:
        raise ContainerNotFoundError(container_id)
    if action == "read" and not can_read(role):
        raise ProjectAccessDeniedError("You do not have read access to this container.")
    if action == "write" and not can_write(role):
        raise ProjectAccessDeniedError("You do not have permission to modify this container.")
    return info.model_copy(update={"access_role": role.value})


def container_visible_to_user(
    info: ContainerInfo,
    *,
    project_ids: set[uuid.UUID],
    user_id: uuid.UUID,
) -> bool:
    label_value = info.labels.get(VELA_PROJECT_LABEL)
    if label_value:
        try:
            return uuid.UUID(label_value) in project_ids
        except ValueError:
            return False
    owner_label = info.labels.get(VELA_OWNER_LABEL)
    return owner_label == str(user_id)


async def list_accessible_project_ids(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> set[uuid.UUID]:
    from app.core.projects.repository import list_project_ids_for_user

    return set(await list_project_ids_for_user(session, user_id))
