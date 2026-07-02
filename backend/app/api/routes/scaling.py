"""Auto-scaling policy API: read and update per-container scaling policies."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_orchestrator
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.models import ScalingPolicyConfig, ScalingPolicyInfo
from app.core.projects.access import list_accessible_project_ids
from app.core.scaling.policy_repository import (
    get_policy,
    list_policies_for_container_names,
    upsert_policy,
)
from app.db.models import User

router = APIRouter()


@router.get("/policies", response_model=list[ScalingPolicyInfo])
async def list_scaling_policies(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> list[ScalingPolicyInfo]:
    """Return scaling policies for containers the caller can access."""
    project_ids = await list_accessible_project_ids(session, current_user.id)
    containers = await orchestrator.list(
        project_ids=project_ids,
        user_id=current_user.id,
    )
    container_names = {container.name for container in containers}
    return await list_policies_for_container_names(session, container_names)


@router.get(
    "/policies/{container_name}",
    response_model=ScalingPolicyInfo,
)
async def get_scaling_policy(
    container_name: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> ScalingPolicyInfo:
    """Return the auto-scaling policy for a container."""
    policy = await get_policy(session, container_name)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scaling policy found for container '{container_name}'.",
        )
    return policy


@router.put(
    "/policies/{container_name}",
    response_model=ScalingPolicyInfo,
)
async def update_scaling_policy(
    container_name: str,
    body: ScalingPolicyConfig,
    session: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> ScalingPolicyInfo:
    """Create or update the auto-scaling policy for a container."""
    return await upsert_policy(session, container_name, body)
