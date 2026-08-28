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
    AnalyzeRepoRequest,
    AnalyzeRepoResponse,
    ManifestParseRequest,
    ManifestParseResponse,
    StackCreate,
    StackPublic,
    StackServiceCreate,
    StackServicePublic,
)
from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import ProjectAccessDeniedError
from app.core.projects.enums import can_write
from app.core.projects.repository import get_personal_project_id, require_membership
from app.core.stacks.manifest_parser import parse_manifest
from app.core.stacks.repo_analysis import analyze_repo_stack
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
            git_branch=s.git_branch,
            container_port=s.container_port,
            env_vars=s.env_vars,
            command=s.command,
            public_route=s.public_route,
            depends_on=s.depends_on,
            volumes=[v.model_dump() for v in s.volumes],
            scaling_policy=s.scaling_policy.model_dump() if s.scaling_policy else None,
            build_override=s.build_override.model_dump() if s.build_override else None,
        )
        for s in body.services
    ]

    stack = await create_stack(session, project_id, body.name, services, body.child_stack_ids)
    result = _stack_to_public(stack, body.child_stack_ids or [])
    await session.commit()
    return result


@router.post("/parse-manifest", response_model=ManifestParseResponse)
async def parse_manifest_route(
    body: ManifestParseRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> ManifestParseResponse:
    _ = current_user
    services, warnings, manifest_kind = parse_manifest(body.yaml_content)
    if not services:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Manifest contains no valid services.",
        )
    return ManifestParseResponse(
        services=[_orm_service_to_create(service) for service in services],
        warnings=warnings,
        manifest_kind=manifest_kind,
    )


@router.post("/analyze-repo", response_model=AnalyzeRepoResponse)
async def analyze_repo_route(
    body: AnalyzeRepoRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
) -> AnalyzeRepoResponse:
    from app.api.routes.containers import _github_token_for_url

    access_token = await _github_token_for_url(session, current_user, body.git_url)
    analysis = await analyze_repo_stack(
        image_builder,
        git_url=body.git_url,
        git_branch=body.git_branch,
        access_token=access_token,
    )
    return AnalyzeRepoResponse(
        services=[_orm_service_to_create(service) for service in analysis.services],
        warnings=analysis.warnings,
        manifest_kind=analysis.manifest_kind,
        manifest_path=analysis.manifest_path,
        summary_hint=analysis.summary_hint,
    )


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
            git_branch=s.git_branch,
            container_port=s.container_port,
            env_vars=s.env_vars,
            command=s.command,
            public_route=s.public_route,
            depends_on=s.depends_on,
            volumes=[v.model_dump() for v in s.volumes],
            scaling_policy=s.scaling_policy.model_dump() if s.scaling_policy else None,
            build_override=s.build_override.model_dump() if s.build_override else None,
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


def _orm_service_to_create(service: StackService) -> StackServiceCreate:
    volumes = service.volumes or []
    scaling = service.scaling_policy
    source_kind = service.source_kind
    if source_kind not in ("image", "git", "dockerfile_template"):
        source_kind = "image"
    return StackServiceCreate(
        service_name=service.service_name,
        source_kind=source_kind,  # type: ignore[arg-type]
        source_ref=service.source_ref,
        git_branch=service.git_branch,
        container_port=service.container_port or 80,
        env_vars=dict(service.env_vars or {}),
        command=service.command,
        public_route=bool(service.public_route),
        depends_on=service.depends_on,
        volumes=volumes or [],
        scaling_policy=scaling,
        build_override=service.build_override,
    )


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
                git_branch=s.git_branch,
                container_port=s.container_port,
                env_vars=s.env_vars,
                command=s.command,
                public_route=s.public_route,
                depends_on=s.depends_on,
                volumes=s.volumes,
                scaling_policy=s.scaling_policy,
                build_override=s.build_override,
            )
            for s in stack.services
        ],
        child_stack_ids=child_stack_ids
        if child_stack_ids is not None
        else [c.child_stack_id for c in stack.compositions_parent],
    )
