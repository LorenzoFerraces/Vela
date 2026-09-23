"""Deploy job status endpoints for async 202 deployments."""

from __future__ import annotations

import uuid
from collections.abc import Coroutine
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_deploy_jobs
from app.api.schemas import DeployJobPublic
from app.core.deploy.jobs import DeployJobRegistry
from app.core.projects.repository import list_project_ids_for_user
from app.db.models import User

router = APIRouter()


async def spawn_deploy_worker(
    registry: DeployJobRegistry,
    job_id: str,
    worker: Callable[..., Coroutine[Any, Any, None]],
    *worker_args: Any,
) -> None:
    """Start the worker after the response is sent so its DB session never
    overlaps the request sessions' teardown on the shared test connection."""
    registry.spawn(job_id, worker(*worker_args))


@router.get("/active", response_model=list[DeployJobPublic])
async def list_active_deploy_jobs(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    registry: Annotated[DeployJobRegistry, Depends(get_deploy_jobs)],
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[DeployJobPublic]:
    """List the caller's in-flight and recently finished deploy jobs."""
    accessible = set(
        await list_project_ids_for_user(session, current_user.id)
    )
    if project_id is not None and project_id not in accessible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found.")

    jobs = registry.active(project_ids=accessible)
    if project_id is not None:
        jobs = [job for job in jobs if job.project_id == project_id]
    return [DeployJobPublic.model_validate(job) for job in jobs]
