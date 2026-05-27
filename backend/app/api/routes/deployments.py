"""Deployment history API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import DeploymentDiffResponse, DeploymentRecordPublic
from app.core import deployment_history
from app.db.models import User

router = APIRouter()


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
