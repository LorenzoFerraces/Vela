"""Container orchestration API backed by :class:`~app.core.docker_orchestrator.DockerOrchestrator`."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import get_orchestrator
from app.api.git_ops import git_shallow_clone, rm_tree
from app.api.schemas import RunFromSourceRequest, RunFromSourceResponse
from app.core.enums import ContainerStatus
from app.core.models import (
    ContainerInfo,
    ContainerStats,
    DeployConfig,
    HealthResult,
    PortMapping,
)
from app.core.orchestrator import ContainerOrchestrator

router = APIRouter()


def _infer_source_kind(source: str) -> tuple[str, str]:
    """Return ``(\"git\"|\"image\", stripped_source)``."""
    stripped = source.strip()
    if stripped.startswith(("git@", "http://", "https://", "ssh://")):
        return "git", stripped
    return "image", stripped


def _deploy_config_for_image(
    *,
    image: str,
    container_name: str | None,
    host_port: int | None,
    container_port: int,
) -> DeployConfig:
    ports: list[PortMapping] = []
    if host_port is not None:
        ports.append(PortMapping(host_port=host_port, container_port=container_port))
    return DeployConfig(
        image=image,
        name=container_name,
        ports=ports,
    )


@router.get("/", response_model=list[ContainerInfo])
async def list_containers(
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    container_status: Annotated[
        ContainerStatus | None,
        Query(alias="status", description="Filter by container status"),
    ] = None,
) -> list[ContainerInfo]:
    """List Vela-managed containers, optionally filtered by status."""
    return await orchestrator.list(status=container_status)


@router.post("/deploy", response_model=ContainerInfo)
async def deploy(
    config: DeployConfig,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> ContainerInfo:
    """Create and start a container from configuration."""
    return await orchestrator.deploy(config)


@router.post("/run", response_model=RunFromSourceResponse)
async def run_from_user_source(
    body: RunFromSourceRequest,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> RunFromSourceResponse:
    """Pull or build an image from ``source``, then deploy a container.

    * **Image** — registry reference (e.g. ``nginx:alpine``). The image is
      pulled if missing, then a container is started.
    * **Git URL** — shallow clone and ``docker build`` in the repo root; then
      a container is started from the new image tag.
    """
    kind, source = _infer_source_kind(body.source)

    if kind == "image":
        cfg = _deploy_config_for_image(
            image=source,
            container_name=body.container_name,
            host_port=body.host_port,
            container_port=body.container_port,
        )
        info = await orchestrator.deploy(cfg)
        return RunFromSourceResponse(container=info, kind="image", image=source)

    tmp_root = Path(tempfile.mkdtemp(prefix="vela-git-"))
    clone_dest = tmp_root / "repo"
    tag = f"vela/gitbuild:{uuid.uuid4().hex[:12]}"
    try:
        await git_shallow_clone(url=source, branch=body.git_branch, dest=clone_dest)
        await orchestrator.build_image(str(clone_dest), tag=tag)
    finally:
        rm_tree(tmp_root)

    cfg = _deploy_config_for_image(
        image=tag,
        container_name=body.container_name,
        host_port=body.host_port,
        container_port=body.container_port,
    )
    info = await orchestrator.deploy(cfg)
    return RunFromSourceResponse(container=info, kind="git", image=tag)


@router.get("/{container_id}", response_model=ContainerInfo)
async def get_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> ContainerInfo:
    """Return detailed information about a single managed container."""
    return await orchestrator.get(container_id)


@router.post("/{container_id}/start", response_model=ContainerInfo)
async def start_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> ContainerInfo:
    """Start a stopped container."""
    return await orchestrator.start(container_id)


@router.post("/{container_id}/stop", response_model=ContainerInfo)
async def stop_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    timeout: int = 10,
) -> ContainerInfo:
    """Gracefully stop a running container."""
    return await orchestrator.stop(container_id, timeout=timeout)


@router.post("/{container_id}/restart", response_model=ContainerInfo)
async def restart_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    timeout: int = 10,
) -> ContainerInfo:
    """Restart a container."""
    return await orchestrator.restart(container_id, timeout=timeout)


@router.delete("/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    force: bool = False,
) -> Response:
    """Remove a container."""
    await orchestrator.remove(container_id, force=force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{container_id}/logs", response_model=dict[str, str])
async def container_logs(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    tail: int = 100,
) -> dict[str, str]:
    """Return recent log lines for a container."""
    text = await orchestrator.logs(container_id, tail=tail)
    return {"logs": text}


@router.get("/{container_id}/stats", response_model=ContainerStats)
async def container_stats(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> ContainerStats:
    """Return resource usage snapshot for a container."""
    return await orchestrator.get_stats(container_id)


@router.get("/{container_id}/health", response_model=HealthResult)
async def container_health(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> HealthResult:
    """Return latest health check result for a container."""
    return await orchestrator.get_health(container_id)
