"""Container orchestration API backed by :class:`~app.core.docker_orchestrator.DockerOrchestrator`."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    get_image_builder,
    get_orchestrator,
    get_traffic_router,
)
from app.api.route_wiring import (
    backend_port_for_route,
    register_route_for_deployed_container,
    remove_route_for_container_name,
)
from app.api.schemas import (
    ContainerDeployResponse,
    ImageAvailabilityResponse,
    RunFromSourceRequest,
    RunFromSourceResponse,
)
from app.core.docker_orchestrator import VELA_OWNER_LABEL
from app.core.public_route_host import (
    apply_public_route_to_deploy_config,
    build_public_url,
    read_public_route_settings,
)
from app.core.enums import ContainerStatus, RestartPolicy
from app.core.exceptions import (
    CloneError,
    ContainerNotFoundError,
    ImageNotFoundError,
    RegistryAccessDeniedError,
)
from app.core.default_image_builder import DefaultImageBuilder
from app.core.models import (
    ContainerInfo,
    ContainerStats,
    DeployConfig,
    HealthResult,
    PortMapping,
    ProjectSource,
)
from app.core.oauth import decrypt_identity_token, get_github_identity
from app.core.orchestrator import ContainerOrchestrator
from app.core.traffic_router import TrafficRouter
from app.db.models import User

router = APIRouter()


def _with_owner_label(config: DeployConfig, owner_id: str) -> DeployConfig:
    """Return a copy of ``config`` whose labels carry ``vela.owner_id=owner_id``."""
    labels = dict(config.labels)
    labels[VELA_OWNER_LABEL] = owner_id
    return config.model_copy(update={"labels": labels})


async def _require_owned(
    orchestrator: ContainerOrchestrator,
    container_id: str,
    current_user: User,
) -> ContainerInfo:
    """Load a container and confirm it belongs to ``current_user`` (404 otherwise)."""
    info = await orchestrator.get(container_id)
    if info.labels.get(VELA_OWNER_LABEL) != str(current_user.id):
        raise ContainerNotFoundError(container_id)
    return info


async def _deploy_and_maybe_wire_route(
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    config: DeployConfig,
) -> tuple[ContainerInfo, bool, str | None]:
    """Deploy then register Traefik route; roll back the container if wiring fails."""
    info = await orchestrator.deploy(config)
    route_host = (config.route_host or "").strip()
    if not route_host:
        return info, False, None
    try:
        await register_route_for_deployed_container(
            traffic_router=traffic_router,
            container_info=info,
            route_host=route_host,
            path_prefix=config.route_path_prefix,
            backend_port=backend_port_for_route(config),
            tls_enabled=config.route_tls,
        )
    except Exception:
        await orchestrator.remove(info.id, force=True)
        raise
    public_url = None
    if config.public_route:
        _, scheme, _ = read_public_route_settings()
        public_url = build_public_url(
            scheme=scheme,
            host=route_host,
            path_prefix=config.route_path_prefix,
        )
    return info, True, public_url


def _infer_source_kind(source: str) -> tuple[str, str]:
    """Return ``(\"git\"|\"image\", stripped_source)``."""
    stripped = source.strip()
    if stripped.startswith(("git@", "http://", "https://", "ssh://")):
        return "git", stripped
    return "image", stripped


def _is_github_https_url(source: str) -> bool:
    """True for the HTTPS forms we can authenticate with a stored access token."""
    try:
        parsed = urlparse(source)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host == "github.com" or host.endswith(".github.com")


async def _github_token_for_url(
    session: AsyncSession, user: User, source: str
) -> str | None:
    """Decrypt the user's GitHub token if ``source`` is a GitHub HTTPS URL."""
    if not _is_github_https_url(source):
        return None
    identity = await get_github_identity(session, user.id)
    if identity is None:
        return None
    return decrypt_identity_token(identity)


def _looks_like_auth_failure(error_message: str) -> bool:
    lowered = error_message.lower()
    auth_markers = (
        "authentication failed",
        "could not read username",
        "terminal prompts disabled",
        "http 401",
        "http 403",
        "403",
        "401",
        "permission denied",
        "repository not found",
    )
    return any(marker in lowered for marker in auth_markers)


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
        container_listen_port=container_port,
    )


@router.get("/", response_model=list[ContainerInfo])
async def list_containers(
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    container_status: Annotated[
        ContainerStatus | None,
        Query(alias="status", description="Filter by container status"),
    ] = None,
) -> list[ContainerInfo]:
    """List the caller's Vela-managed containers, optionally filtered by status."""
    return await orchestrator.list(
        status=container_status, owner_id=str(current_user.id)
    )


@router.get("/image/availability", response_model=ImageAvailabilityResponse)
async def image_availability(
    ref: Annotated[str, Query(min_length=1, max_length=2048, description="Docker image reference.")],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> ImageAvailabilityResponse:
    """Check whether a registry image reference exists (local engine or remote manifest).

    Git clone URLs are returned with ``checked=false`` so the UI can skip gating.
    """
    stripped = ref.strip()
    kind, source = _infer_source_kind(stripped)
    if kind == "git":
        return ImageAvailabilityResponse(
            ref=source,
            available=True,
            checked=False,
            detail=None,
        )
    try:
        await orchestrator.verify_image_reference_available(source)
    except ImageNotFoundError as exc:
        content = exc.api_response_content()
        return ImageAvailabilityResponse(
            ref=source,
            available=False,
            checked=True,
            can_attempt_deploy=False,
            detail=str(content["detail"]),
            error_code=str(content["error_code"]),
            hints=None,
            registry_detail=None,
        )
    except RegistryAccessDeniedError as exc:
        content = exc.api_response_content()
        return ImageAvailabilityResponse(
            ref=source,
            available=False,
            checked=True,
            can_attempt_deploy=True,
            detail=str(content["detail"]),
            error_code=str(content["error_code"]),
            hints=None,
            registry_detail=None,
        )
    return ImageAvailabilityResponse(ref=source, available=True, checked=True, detail=None)


@router.post("/deploy", response_model=ContainerDeployResponse)
async def deploy(
    config: DeployConfig,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ContainerDeployResponse:
    """Create and start a container from configuration."""
    config = _with_owner_label(config, str(current_user.id))
    config = await apply_public_route_to_deploy_config(config, traffic_router)
    info, route_wired, public_url = await _deploy_and_maybe_wire_route(
        orchestrator, traffic_router, config
    )
    return ContainerDeployResponse(
        container=info,
        route_wired=route_wired,
        public_url=public_url,
    )


@router.post("/run", response_model=RunFromSourceResponse)
async def run_from_user_source(
    body: RunFromSourceRequest,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RunFromSourceResponse:
    """Pull or build an image from ``source``, then deploy a container.

    * **Image** — registry reference (e.g. ``nginx:alpine``). The image is
      pulled if missing, then a container is started.
    * **Git URL** — shallow clone, ensure a ``Dockerfile`` (existing or
      generated from ``package.json`` / Python / Go markers), ``docker build``,
      then start a container from the new image tag.

    For GitHub HTTPS URLs we transparently use the caller's stored OAuth token
    (when they have connected GitHub in Settings) so private repos clone too.
    """
    kind, source = _infer_source_kind(body.source)

    if kind == "image":
        cfg = _deploy_config_for_image(
            image=source,
            container_name=body.container_name,
            host_port=body.host_port,
            container_port=body.container_port,
        ).model_copy(
            update={
                "route_host": None if body.public_route else body.route_host,
                "route_path_prefix": body.route_path_prefix,
                "route_tls": body.route_tls if not body.public_route else False,
                "public_route": body.public_route,
            }
        )
        cfg = _with_owner_label(cfg, str(current_user.id))
        cfg = await apply_public_route_to_deploy_config(cfg, traffic_router)
        info, route_wired, public_url = await _deploy_and_maybe_wire_route(
            orchestrator, traffic_router, cfg
        )
        return RunFromSourceResponse(
            container=info,
            kind="image",
            image=source,
            route_wired=route_wired,
            public_url=public_url,
        )

    access_token = await _github_token_for_url(session, current_user, source)
    tag = f"vela/gitbuild:{uuid.uuid4().hex[:12]}"
    try:
        build_result = await image_builder.build_from_source(
            ProjectSource(git_url=source, branch=body.git_branch),
            tag=tag,
            access_token=access_token,
        )
    except CloneError as exc:
        if (
            access_token is None
            and _is_github_https_url(source)
            and _looks_like_auth_failure(str(exc))
        ):
            raise CloneError(
                source,
                "Repository looks private. Connect GitHub in Settings to deploy private repos.",
            ) from exc
        raise

    cfg = _deploy_config_for_image(
        image=build_result.image_tag,
        container_name=body.container_name,
        host_port=body.host_port,
        container_port=body.container_port,
    ).model_copy(
        update={
            "restart_policy": RestartPolicy.UNLESS_STOPPED,
            "route_host": None if body.public_route else body.route_host,
            "route_path_prefix": body.route_path_prefix,
            "route_tls": body.route_tls if not body.public_route else False,
            "public_route": body.public_route,
        }
    )
    cfg = _with_owner_label(cfg, str(current_user.id))
    cfg = await apply_public_route_to_deploy_config(cfg, traffic_router)
    info, route_wired, public_url = await _deploy_and_maybe_wire_route(
        orchestrator, traffic_router, cfg
    )
    return RunFromSourceResponse(
        container=info,
        kind="git",
        image=build_result.image_tag,
        route_wired=route_wired,
        public_url=public_url,
    )


@router.get("/{container_id}", response_model=ContainerInfo)
async def get_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ContainerInfo:
    """Return detailed information about a single managed container."""
    return await _require_owned(orchestrator, container_id, current_user)


@router.post("/{container_id}/start", response_model=ContainerInfo)
async def start_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ContainerInfo:
    """Start a stopped container."""
    await _require_owned(orchestrator, container_id, current_user)
    return await orchestrator.start(container_id)


@router.post("/{container_id}/stop", response_model=ContainerInfo)
async def stop_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    timeout: int = 10,
) -> ContainerInfo:
    """Gracefully stop a running container."""
    await _require_owned(orchestrator, container_id, current_user)
    return await orchestrator.stop(container_id, timeout=timeout)


@router.post("/{container_id}/restart", response_model=ContainerInfo)
async def restart_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    timeout: int = 10,
) -> ContainerInfo:
    """Restart a container."""
    await _require_owned(orchestrator, container_id, current_user)
    return await orchestrator.restart(container_id, timeout=timeout)


@router.delete("/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
    current_user: Annotated[User, Depends(get_current_user)],
    force: bool = False,
) -> Response:
    """Remove a container and drop any Traefik route keyed by its name."""
    info = await _require_owned(orchestrator, container_id, current_user)
    await remove_route_for_container_name(
        traffic_router=traffic_router,
        container_name=info.name,
    )
    await orchestrator.remove(container_id, force=force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{container_id}/logs", response_model=dict[str, str])
async def container_logs(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    tail: int = 100,
) -> dict[str, str]:
    """Return recent log lines for a container."""
    await _require_owned(orchestrator, container_id, current_user)
    text = await orchestrator.logs(container_id, tail=tail)
    return {"logs": text}


@router.get("/{container_id}/stats", response_model=ContainerStats)
async def container_stats(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ContainerStats:
    """Return resource usage snapshot for a container."""
    await _require_owned(orchestrator, container_id, current_user)
    return await orchestrator.get_stats(container_id)


@router.get("/{container_id}/health", response_model=HealthResult)
async def container_health(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> HealthResult:
    """Return latest health check result for a container."""
    await _require_owned(orchestrator, container_id, current_user)
    return await orchestrator.get_health(container_id)
