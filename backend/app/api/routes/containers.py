"""Container orchestration API (stubs until a concrete orchestrator exists)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.core.enums import ContainerStatus
from app.core.models import DeployConfig

router = APIRouter()


def _not_implemented() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet — no concrete orchestrator is wired.",
    )


@router.get("/")
async def list_containers(
    container_status: Annotated[
        ContainerStatus | None,
        Query(alias="status", description="Filter by container status"),
    ] = None,
) -> None:
    """List managed containers, optionally filtered by status."""
    _not_implemented()


@router.get("/{container_id}")
async def get_container(container_id: str) -> None:
    """Return detailed information about a single container."""
    _not_implemented()


@router.post("/deploy")
async def deploy(config: DeployConfig) -> None:
    """Create and start a container from configuration."""
    _not_implemented()


@router.post("/{container_id}/start")
async def start_container(container_id: str) -> None:
    """Start a stopped container."""
    _not_implemented()


@router.post("/{container_id}/stop")
async def stop_container(container_id: str, timeout: int = 10) -> None:
    """Gracefully stop a running container."""
    _not_implemented()


@router.post("/{container_id}/restart")
async def restart_container(container_id: str, timeout: int = 10) -> None:
    """Restart a container."""
    _not_implemented()


@router.delete("/{container_id}")
async def remove_container(container_id: str, force: bool = False) -> None:
    """Remove a container."""
    _not_implemented()


@router.get("/{container_id}/logs")
async def container_logs(container_id: str, tail: int = 100) -> None:
    """Return recent log lines for a container."""
    _not_implemented()


@router.get("/{container_id}/stats")
async def container_stats(container_id: str) -> None:
    """Return resource usage snapshot for a container."""
    _not_implemented()


@router.get("/{container_id}/health")
async def container_health(container_id: str) -> None:
    """Return latest health check result for a container."""
    _not_implemented()
