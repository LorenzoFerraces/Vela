"""Auto-scaling policy API: read and update per-container scaling policies."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    get_orchestrator,
    get_traffic_router,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.enums import ScalingMetric
from app.core.models import ScalingPolicyConfig, ScalingPolicyInfo
from app.core.monitoring.edge_requests import get_edge_request_rates
from app.core.projects.access import (
    list_accessible_project_ids,
    require_container_access,
)
from app.core.scaling.policy_repository import (
    get_policy,
    list_policies_for_container_names,
    upsert_policy,
)
from app.core.traffic.traffic_router import NoopTrafficRouter
from app.db.models import User

router = APIRouter()


def _with_signal_status(info: ScalingPolicyInfo) -> ScalingPolicyInfo:
    """Flag RPS policies whose request-rate signal is unavailable."""
    if info.metric is ScalingMetric.REQUESTS_PER_SECOND and not isinstance(
        get_traffic_router(), NoopTrafficRouter
    ):
        info.signal_unavailable = not get_edge_request_rates().available
    return info


async def _require_accessible_container_name(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    current_user: User,
    container_name: str,
) -> None:
    project_ids = await list_accessible_project_ids(session, current_user.id)
    containers = await orchestrator.list(
        project_ids=project_ids,
        user_id=current_user.id,
    )
    accessible_names = {container.name for container in containers}
    if container_name not in accessible_names:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No container found with name '{container_name}'.",
        )


async def require_container_write_access(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    current_user: User,
    container_name: str,
) -> None:
    """Reject callers who can only view the container."""
    info = await orchestrator.get_by_name(container_name) if hasattr(
        orchestrator, "get_by_name"
    ) else next(
        (
            container
            for container in await orchestrator.list(user_id=current_user.id)
            if container.name == container_name
        ),
        None,
    )
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Container not found.")
    await require_container_access(
        session, orchestrator, current_user, info.id, action="write"
    )


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
    policies = await list_policies_for_container_names(session, container_names)
    return [_with_signal_status(info) for info in policies]


@router.get(
    "/policies/{container_name}",
    response_model=ScalingPolicyInfo,
)
async def get_scaling_policy(
    container_name: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> ScalingPolicyInfo:
    """Return the auto-scaling policy for a container."""
    await _require_accessible_container_name(
        session, orchestrator, current_user, container_name
    )
    policy = await get_policy(session, container_name)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scaling policy found for container '{container_name}'.",
        )
    return _with_signal_status(policy)


@router.put(
    "/policies/{container_name}",
    response_model=ScalingPolicyInfo,
)
async def update_scaling_policy(
    container_name: str,
    body: ScalingPolicyConfig,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> ScalingPolicyInfo:
    """Create or update the auto-scaling policy for a container."""
    await _require_accessible_container_name(
        session, orchestrator, current_user, container_name
    )
    await require_container_write_access(
        session, orchestrator, current_user, container_name
    )
    return _with_signal_status(await upsert_policy(session, container_name, body))
