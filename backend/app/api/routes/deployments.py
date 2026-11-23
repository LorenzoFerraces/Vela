"""Deployment history API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    get_orchestrator,
    get_traffic_router,
)
from app.api.routes.containers import (
    _apply_deploy_labels,
    _deploy_and_maybe_wire_route,
    _persist_run_deployment,
)
from app.api.schemas import (
    DeploymentDiffResponse,
    DeploymentRecordPublic,
    DeploymentUpdateDryRunResponse,
    DeploymentUpdateRequest,
    RunFromSourceRequest,
)
from app.core.audit.service import emit_audit_log
from app.core.containers.docker_orchestrator import VELA_OWNER_LABEL, VELA_PROJECT_LABEL
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.deploy import deployment_history
from app.core.deploy.deployment_history import _diff_env
from app.core.deploy.secret_resolution import runtime_config_with_secrets
from app.core.exceptions import DeploymentConfigChangeRequiresRecreateError
from app.core.models import DeployConfig
from app.core.projects.repository import get_personal_project_id
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import User

router = APIRouter()

_PROTECTED_LABELS = (VELA_OWNER_LABEL, VELA_PROJECT_LABEL)


def _validate_update(update: DeploymentUpdateRequest) -> dict[str, object]:
    """Return mutable fields, rejecting identity changes and managed labels."""
    mutable, rejected = deployment_history.classify_update(
        update.model_dump(exclude_none=True)
    )
    managed = sorted(
        key for key in (update.labels or {}) if key in _PROTECTED_LABELS
    )
    if managed:
        raise DeploymentConfigChangeRequiresRecreateError(
            f"Cannot edit Vela-managed label(s): {', '.join(managed)}. "
            "These are applied automatically on deploy."
        )
    if rejected:
        raise DeploymentConfigChangeRequiresRecreateError(
            "These fields cannot be updated in place; recreate the deployment: "
            + ", ".join(rejected)
            + "."
        )
    return mutable


async def _load_candidate(
    session: AsyncSession,
    current_user: User,
    deployment_id: uuid.UUID,
    body: DeploymentUpdateRequest,
) -> tuple[DeploymentRecordPublic, DeployConfig, DeployConfig]:
    """Return the scoped record, its persisted config snapshot, and the update candidate."""
    record = await deployment_history.get_deployment(
        session, current_user.id, deployment_id
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Deployment not found.")
    snapshot = await deployment_history.load_deploy_config_snapshot(
        session, record.container_id
    )
    if snapshot is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Deployment config snapshot not found."
        )
    candidate = snapshot.model_copy(update=_validate_update(body))
    return record, snapshot, candidate


@router.get("/", response_model=list[DeploymentRecordPublic])
async def list_deployment_history(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    container_name: Annotated[
        str | None,
        Query(max_length=128, description="Filter by container name"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[DeploymentRecordPublic]:
    return await deployment_history.list_deployments(
        session,
        current_user.id,
        container_name=container_name,
        limit=limit,
    )


@router.get("/{deployment_id}", response_model=DeploymentRecordPublic)
async def get_deployment_record(
    deployment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DeploymentRecordPublic:
    row = await deployment_history.get_deployment(
        session, current_user.id, deployment_id
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Deployment not found.")
    return row


@router.get("/{left_id}/diff/{right_id}", response_model=DeploymentDiffResponse)
async def diff_deployment_records(
    left_id: uuid.UUID,
    right_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DeploymentDiffResponse:
    diff = await deployment_history.diff_deployments(
        session,
        current_user.id,
        left_id,
        right_id,
    )
    if diff is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Deployment not found.")
    return diff


@router.post("/{deployment_id}/dry-run", response_model=DeploymentUpdateDryRunResponse)
async def dry_run_deployment_update(
    deployment_id: uuid.UUID,
    body: DeploymentUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DeploymentUpdateDryRunResponse:
    record, snapshot, candidate = await _load_candidate(
        session, current_user, deployment_id, body
    )
    return DeploymentUpdateDryRunResponse(
        left_id=record.id,
        right_id=record.id,
        env=_diff_env(snapshot.env_vars, candidate.env_vars),
        dockerfile_diff=[],
        config={
            field: diff.after
            for field, diff in deployment_history.diff_config_fields(
                snapshot, candidate
            ).items()
        },
    )


@router.patch("/{deployment_id}", response_model=DeploymentRecordPublic)
async def update_deployment_config(
    deployment_id: uuid.UUID,
    body: DeploymentUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
) -> DeploymentRecordPublic:
    record, _snapshot, candidate = await _load_candidate(
        session, current_user, deployment_id, body
    )
    project_id = (
        record.project_id
        or await get_personal_project_id(session, current_user)
    )
    candidate = _apply_deploy_labels(
        candidate, owner_id=str(current_user.id), project_id=project_id
    )
    runtime_config = await runtime_config_with_secrets(
        session, candidate, owner_user_id=current_user.id, project_id=record.project_id,
    )
    info, _route_wired, public_url = await _deploy_and_maybe_wire_route(
        orchestrator, traffic_router, runtime_config
    )
    run_body = RunFromSourceRequest.model_validate(
        {
            "source_kind": "image",
            "image_ref": candidate.image,
            "container_name": record.container_name,
            "container_port": record.container_port,
            "env_vars": candidate.env_vars,
            "command": candidate.command,
        }
    )
    await _persist_run_deployment(
        session,
        current_user,
        run_body,
        info,
        project_id=project_id,
        source_kind=record.source_kind,
        source_ref=record.source_ref,
        image_tag=record.image_tag,
        dockerfile_snapshot=record.dockerfile_snapshot,
        public_url=public_url,
        deploy_config=candidate.model_dump(mode="json"),
    )
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="deployment.update",
        target_type="container",
        target_id=info.id,
        details={"container_id": record.container_id},
    )
    await session.commit()
    rows = await deployment_history.list_deployments(
        session, current_user.id, limit=1
    )
    return rows[0]
