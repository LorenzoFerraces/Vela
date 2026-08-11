"""Stack management API."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    get_current_user,
    get_db,
    get_image_builder,
    get_orchestrator,
    get_traffic_router,
)
from app.api.schemas import (
    ComposeImportRequest,
    ComposeImportResponse,
    StackCreate,
    StackPublic,
    StackServicePublic,
)
from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import ProjectAccessDeniedError, StackNotFoundError
from app.core.projects.enums import can_write
from app.core.projects.repository import get_personal_project_id, require_membership
from app.core.stacks.compose_parser import parse_compose
from app.core.stacks.deploy import deploy_stack
from app.core.stacks.repository import (
    create_stack,
    delete_stack,
    get_stack,
    list_stacks,
    update_stack,
)
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import Stack, StackService, User

logger = logging.getLogger(__name__)

router = APIRouter()


async def _require_stack_write_access(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
) -> None:
    membership = await require_membership(session, project_id=project_id, user_id=user_id)
    if not can_write(membership.role):
        raise ProjectAccessDeniedError(
            f"You do not have permission to {action} stacks in this project."
        )


@router.get("/", response_model=list[StackPublic])
async def list_user_stacks(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[StackPublic]:
    stacks = await list_stacks(session, current_user.id)
    return [_stack_to_public(s) for s in stacks]


@router.post("/", response_model=StackPublic, status_code=status.HTTP_201_CREATED)
async def create_user_stack(
    body: StackCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> StackPublic:
    project_id = body.project_id or await get_personal_project_id(session, current_user)
    await _require_stack_write_access(
        session,
        project_id=project_id,
        user_id=current_user.id,
        action="create",
    )

    services = [
        StackService(
            service_name=s.service_name,
            source_kind=s.source_kind,
            source_ref=s.source_ref,
            container_port=s.container_port,
            env_vars=s.env_vars,
            command=s.command,
            public_route=s.public_route,
            depends_on=s.depends_on,
            volumes=[v.model_dump() for v in s.volumes],
            scaling_policy=s.scaling_policy.model_dump() if s.scaling_policy else None,
        )
        for s in body.services
    ]

    stack = await create_stack(session, project_id, body.name, services, body.child_stack_ids)
    result = _stack_to_public(stack, body.child_stack_ids or [])
    await session.commit()
    return result


@router.post("/import-compose", response_model=ComposeImportResponse, status_code=status.HTTP_201_CREATED)
async def import_compose(
    body: ComposeImportRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ComposeImportResponse:
    services, warnings = parse_compose(body.yaml_content)
    if not services:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Compose file contains no valid services.",
        )

    project_id = body.project_id or await get_personal_project_id(session, current_user)
    await _require_stack_write_access(
        session,
        project_id=project_id,
        user_id=current_user.id,
        action="import",
    )

    stack = await create_stack(session, project_id, body.name, services, [])
    result = ComposeImportResponse(stack=_stack_to_public(stack, []), warnings=warnings)
    await session.commit()
    return result


@router.get("/{stack_id}", response_model=StackPublic)
async def get_user_stack(
    stack_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> StackPublic:
    stack = await get_stack(session, stack_id, current_user.id)
    if stack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Stack not found.")
    return _stack_to_public(stack)


@router.put("/{stack_id}", response_model=StackPublic)
async def update_user_stack(
    body: StackCreate,
    stack_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> StackPublic:
    services = [
        StackService(
            service_name=s.service_name,
            source_kind=s.source_kind,
            source_ref=s.source_ref,
            container_port=s.container_port,
            env_vars=s.env_vars,
            command=s.command,
            public_route=s.public_route,
            depends_on=s.depends_on,
            volumes=[v.model_dump() for v in s.volumes],
            scaling_policy=s.scaling_policy.model_dump() if s.scaling_policy else None,
        )
        for s in body.services
    ]

    stack = await update_stack(session, stack_id, current_user.id, body.name, services, body.child_stack_ids)
    result = _stack_to_public(stack)
    await session.commit()
    return result


@router.delete("/{stack_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_stack(
    stack_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> Response:
    stack = await get_stack(session, stack_id, current_user.id)
    if stack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Stack not found.")

    containers = await orchestrator.list()
    containers_by_name = {container.name: container for container in containers}
    for service in stack.services:
        container_name = f"{stack.name}_{service.service_name}"
        container = containers_by_name.get(container_name)
        if container is None:
            continue
        try:
            await orchestrator.stop(container.id, timeout=5)
            await orchestrator.remove(container.id, force=True)
        except Exception:
            logger.warning(
                "Failed to stop/remove stack container %s during delete",
                container_name,
                exc_info=True,
            )

    try:
        await orchestrator.remove_network(stack.network_name)
    except Exception:
        logger.warning(
            "Failed to remove stack network %s during delete",
            stack.network_name,
            exc_info=True,
        )

    await delete_stack(session, stack_id, current_user.id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{stack_id}/deploy", response_model=dict[str, object])
async def deploy_user_stack(
    stack_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
) -> dict[str, object]:
    stack = await get_stack(session, stack_id, current_user.id)
    if stack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Stack not found.")

    await _require_stack_write_access(
        session,
        project_id=stack.project_id,
        user_id=current_user.id,
        action="deploy",
    )

    child_stacks = []
    for comp in stack.compositions_parent:
        result = await session.execute(
            sa_select(Stack)
            .where(Stack.id == comp.child_stack_id)
            .options(selectinload(Stack.services))
        )
        child = result.scalar_one_or_none()
        if child:
            child_stacks.append(child)

    result = await deploy_stack(
        session,
        orchestrator,
        traffic_router,
        image_builder,
        stack,
        current_user,
        child_stacks,
    )
    if result.get("error"):
        detail = str(result["error"])
        failed_service = result.get("failed_service")
        if failed_service:
            detail = f"Deploy failed on service '{failed_service}': {detail}"
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)
    return result


def _stack_to_public(
    stack: Stack,
    child_stack_ids: list[uuid.UUID] | None = None,
) -> StackPublic:
    return StackPublic(
        id=stack.id,
        project_id=stack.project_id,
        name=stack.name,
        network_name=stack.network_name,
        created_at=stack.created_at,
        services=[
            StackServicePublic(
                id=s.id,
                stack_id=s.stack_id,
                service_name=s.service_name,
                source_kind=s.source_kind,
                source_ref=s.source_ref,
                container_port=s.container_port,
                env_vars=s.env_vars,
                command=s.command,
                public_route=s.public_route,
                depends_on=s.depends_on,
                volumes=s.volumes,
                scaling_policy=s.scaling_policy,
            )
            for s in stack.services
        ],
        child_stack_ids=child_stack_ids
        if child_stack_ids is not None
        else [c.child_stack_id for c in stack.compositions_parent],
    )
