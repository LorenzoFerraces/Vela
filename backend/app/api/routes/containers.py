"""Container orchestration API backed by :class:`~app.core.containers.docker_orchestrator.DockerOrchestrator`."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import suppress
from typing import Annotated, Callable
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    Depends,
    File,
    Query,
    Response,
    UploadFile,
    WebSocket,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

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
    ImageSuggestion,
    ImageSuggestionsResponse,
    RunFromSourceRequest,
    RunFromSourceResponse,
    VolumeMountRequest,
    VolumeUploadResponse,
)
from app.core.models import ScalingPolicyInfo
from app.core import user_library
from app.core.auth.service import get_user_by_id
from app.core.auth.tokens import decode_access_token
from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.build.registry_image_suggestions import (
    fetch_docker_hub_suggestions,
    merge_image_suggestions,
)
from app.core.audit.service import emit_audit_log
from app.core.containers.docker_orchestrator import (
    VELA_OWNER_LABEL,
    VELA_PROJECT_LABEL,
    VELA_SOURCE_KIND_LABEL,
    VELA_SOURCE_REF_LABEL,
    with_deploy_source_labels,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.containers.volume_uploads import (
    resolve_volume_upload_path,
    save_volume_upload,
    user_uploads_total_bytes,
    volume_upload_max_bytes,
    volume_upload_user_quota_bytes,
)
from app.core.deploy.deploy_source_display import source_ref_looks_like_uuid
from app.core.deploy.deploy_source_suggestions import (
    DeploySourcesResponse,
    collect_deploy_source_suggestions,
)
from app.core.deploy.deployment_history import (
    DeploymentSnapshot,
    latest_source_by_container_ids,
    record_deployment,
)
from app.core.scaling.policy_repository import upsert_policy
from app.core.enums import ContainerStatus, RestartPolicy
from app.core.exceptions import (
    CloneError,
    ContainerNotFoundError,
    ImageNotFoundError,
    InvalidVolumeUploadPathError,
    NotAuthenticatedError,
    ProjectAccessDeniedError,
    ProviderConnectionError,
    RegistryAccessDeniedError,
    TeamStorageQuotaExceededError,
    VolumeUploadQuotaExceededError,
    VolumeUploadTooLargeError,
)
from app.core.models import (
    ContainerInfo,
    ContainerStats,
    DeployConfig,
    default_listen_port_health_check,
    HealthResult,
    PortMapping,
    ProjectSource,
    VolumeMount,
)
from app.core.oauth import decrypt_identity_token, get_github_identity
from app.core.quotas import (
    effective_quota_bytes,
    enforce_team_storage_capacity,
    format_gib,
    team_storage_usage,
)
from app.core.projects.access import (
    list_accessible_project_ids,
    require_container_access,
)
from app.core.projects.enums import ProjectRole, can_write
from app.core.projects.repository import get_personal_project_id, require_membership
from app.core.traffic.public_route_host import (
    apply_public_route_to_deploy_config,
    build_public_url,
    read_public_route_settings,
)
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import Dockerfile, Project, ProjectMembership, User

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_LOG_TAIL_LINES = 2000
_MAX_EXEC_CONCURRENT = 20
_exec_semaphore = asyncio.Semaphore(_MAX_EXEC_CONCURRENT)
_EXEC_SEMAPHORE_ACQUIRE_TIMEOUT = 10.0
_EXEC_START_FAILURE_MESSAGE = (
    "Could not start a shell in this container. Make sure it is running and "
    "a shell (sh) is installed."
)
_MAX_TERMINAL_DIMENSION = 500


def _exec_max_session_seconds() -> int:
    try:
        return max(1, int(os.getenv("VELA_EXEC_MAX_SESSION_SECONDS", "3600")))
    except ValueError:
        return 3600


def _parse_resize_message(raw: str) -> tuple[int, int] | None:
    """Return (cols, rows) if ``raw`` is a strict resize control frame, else None."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict) or set(parsed) != {"resize"}:
        return None
    resize = parsed["resize"]
    if not isinstance(resize, dict) or set(resize) != {"cols", "rows"}:
        return None
    cols, rows = resize["cols"], resize["rows"]
    if type(cols) is not int or type(rows) is not int:
        return None
    if not (1 <= cols <= _MAX_TERMINAL_DIMENSION and 1 <= rows <= _MAX_TERMINAL_DIMENSION):
        return None
    return cols, rows


def _with_owner_label(config: DeployConfig, owner_id: str) -> DeployConfig:
    """Return a copy of ``config`` whose labels carry ``vela.owner_id=owner_id``."""
    labels = dict(config.labels)
    labels[VELA_OWNER_LABEL] = owner_id
    return config.model_copy(update={"labels": labels})


def _with_project_label(config: DeployConfig, project_id: uuid.UUID) -> DeployConfig:
    labels = dict(config.labels)
    labels[VELA_PROJECT_LABEL] = str(project_id)
    return config.model_copy(update={"labels": labels})


def _apply_deploy_labels(
    config: DeployConfig,
    *,
    owner_id: str,
    project_id: uuid.UUID,
) -> DeployConfig:
    return _with_project_label(_with_owner_label(config, owner_id), project_id)


async def _resolve_deploy_project_id(
    session: AsyncSession,
    user: User,
    body: RunFromSourceRequest,
) -> uuid.UUID:
    project_id = body.project_id or await get_personal_project_id(session, user)
    membership = await require_membership(
        session, project_id=project_id, user_id=user.id
    )
    if not can_write(membership.role):
        raise ProjectAccessDeniedError(
            "You do not have permission to deploy to this project."
        )
    return project_id


async def _resolve_deploy_project_id_for_config(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID | None,
) -> uuid.UUID:
    resolved = project_id or await get_personal_project_id(session, user)
    membership = await require_membership(session, project_id=resolved, user_id=user.id)
    if not can_write(membership.role):
        raise ProjectAccessDeniedError(
            "You do not have permission to deploy to this project."
        )
    return resolved


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
    env_vars: dict[str, str] | None = None,
    command: list[str] | None = None,
    volumes: list[VolumeMount] | None = None,
    cpu_limit: float | None = None,
    memory_limit: int | None = None,
) -> DeployConfig:
    ports: list[PortMapping] = []
    if host_port is not None:
        ports.append(PortMapping(host_port=host_port, container_port=container_port))
    return DeployConfig(
        image=image,
        name=container_name,
        ports=ports,
        container_listen_port=container_port,
        env_vars=env_vars or {},
        command=command,
        volumes=volumes or [],
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        health_check=default_listen_port_health_check(container_port),
    )


def _resolve_deploy_volumes(
    user_id: uuid.UUID,
    volume_requests: list[VolumeMountRequest],
) -> list[VolumeMount]:
    return [
        VolumeMount(
            source=str(resolve_volume_upload_path(user_id, mount.upload_id)),
            target=mount.target,
        )
        for mount in volume_requests
    ]


def _route_updates_from_run_body(body: RunFromSourceRequest) -> dict[str, object]:
    return {
        "route_host": None if body.public_route else body.route_host,
        "route_path_prefix": body.route_path_prefix,
        "route_tls": body.route_tls if not body.public_route else False,
        "public_route": body.public_route,
    }


_DEPLOYMENT_ENV_VALUE_REDACTED = "<REDACTED>"


def _sanitize_url_for_audit(url: str) -> str:
    """Remove userinfo, query, and fragment from URL for audit persistence."""
    try:
        parsed = urlparse(url)
        clean = parsed._replace(netloc=parsed.hostname or "", query="", fragment="")
        return clean.geturl()
    except ValueError:
        return url


def _redacted_env_vars_for_history(env_vars: dict[str, str]) -> dict[str, str]:
    return {key: _DEPLOYMENT_ENV_VALUE_REDACTED for key in env_vars}


async def _persist_run_deployment(
    session: AsyncSession,
    user: User,
    body: RunFromSourceRequest,
    info: ContainerInfo,
    *,
    project_id: uuid.UUID,
    source_kind: str,
    source_ref: str,
    image_tag: str,
    dockerfile_snapshot: str | None,
    public_url: str | None,
) -> None:
    sanitized_env_vars = _redacted_env_vars_for_history(body.env_vars)
    try:
        await record_deployment(
            session,
            user_id=user.id,
            project_id=project_id,
            snapshot=DeploymentSnapshot(
                container_id=info.id,
                container_name=info.name or body.container_name,
                source_kind=source_kind,
                source_ref=source_ref,
                git_branch=body.git_branch if source_kind == "git" else None,
                image_tag=image_tag,
                container_port=body.container_port,
                env_vars=sanitized_env_vars,
                command=list(body.command) if body.command else None,
                dockerfile_snapshot=dockerfile_snapshot,
                public_url=public_url,
                build_override=(
                    body.build_override.model_dump() if body.build_override else None
                ),
            ),
        )
    except Exception:
        logger.exception(
            "Failed to persist deployment history for container %s",
            info.id,
        )


async def _persist_scaling_policy(
    session: AsyncSession,
    container_name: str,
    body: RunFromSourceRequest,
) -> tuple[ScalingPolicyInfo | None, str | None]:
    if body.scaling_policy is None:
        return None, None
    try:
        policy = await upsert_policy(session, container_name, body.scaling_policy)
        return policy, None
    except Exception:
        logger.exception(
            "Failed to persist scaling policy for container %s", container_name
        )
        return None, (
            "Auto-scaling policy could not be saved. "
            "Configure scaling from the container settings or try again."
        )


def _container_project_or_owner(
    info: ContainerInfo,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Return ``(project_id, owner_id)`` parsed from container labels (one may be None)."""
    label_value = info.labels.get(VELA_PROJECT_LABEL)
    if label_value:
        try:
            return uuid.UUID(label_value), None
        except ValueError:
            pass
    owner_label = info.labels.get(VELA_OWNER_LABEL)
    if not owner_label:
        return None, None
    try:
        return None, uuid.UUID(owner_label)
    except ValueError:
        return None, None


async def _enrich_container_source_labels(
    session: AsyncSession,
    user: User,
    containers: list[ContainerInfo],
    project_ids: set[uuid.UUID],
) -> list[ContainerInfo]:
    """Fill ``source_label`` and ``access_role`` for listed containers."""
    history_by_container = await latest_source_by_container_ids(
        session,
        user.id,
        [row.id for row in containers],
        project_ids=project_ids,
    )

    project_or_owner: dict[str, tuple[uuid.UUID | None, uuid.UUID | None]] = {}
    for info in containers:
        project_or_owner[info.id] = _container_project_or_owner(info)
    owner_ids = {
        owner_id for _, owner_id in project_or_owner.values() if owner_id is not None
    }

    personal_project_by_owner: dict[uuid.UUID, uuid.UUID | None] = {}
    if owner_ids:
        result = await session.execute(select(User).where(User.id.in_(owner_ids)))
        for owner in result.scalars():
            personal_project_id = owner.personal_project_id
            if personal_project_id is None:
                personal_project_id = await get_personal_project_id(session, owner)
            personal_project_by_owner[owner.id] = personal_project_id

    project_id_by_container: dict[str, uuid.UUID | None] = {}
    for info in containers:
        project_id, owner_id = project_or_owner[info.id]
        if project_id is None and owner_id is not None:
            project_id = personal_project_by_owner.get(owner_id)
        project_id_by_container[info.id] = project_id

    role_by_project: dict[uuid.UUID, ProjectRole] = {}
    candidate_projects = {
        project_id
        for project_id in project_id_by_container.values()
        if project_id is not None
    }
    if candidate_projects:
        membership_result = await session.execute(
            select(ProjectMembership).where(
                ProjectMembership.user_id == user.id,
                ProjectMembership.project_id.in_(candidate_projects),
            )
        )
        for membership in membership_result.scalars():
            role_by_project[membership.project_id] = ProjectRole(membership.role)

    source_by_container: dict[str, tuple[str | None, str]] = {}
    template_ids: set[uuid.UUID] = set()
    for info in containers:
        source_kind = info.source_kind or info.labels.get(VELA_SOURCE_KIND_LABEL)
        source_ref = info.source_label or info.labels.get(VELA_SOURCE_REF_LABEL) or ""
        if not source_ref and info.id in history_by_container:
            history_kind, history_ref = history_by_container[info.id]
            source_kind = source_kind or history_kind
            source_ref = history_ref
        source_by_container[info.id] = (source_kind, source_ref)
        if (
            source_kind == "dockerfile_template"
            and source_ref_looks_like_uuid(source_ref)
        ):
            template_ids.add(uuid.UUID(source_ref))

    template_names: dict[uuid.UUID, str] = {}
    if template_ids:
        template_result = await session.execute(
            select(Dockerfile).where(
                Dockerfile.owner_id == user.id,
                Dockerfile.id.in_(template_ids),
            )
        )
        for row in template_result.scalars():
            template_names[row.id] = row.name

    enriched: list[ContainerInfo] = []
    for info in containers:
        project_id = project_id_by_container[info.id]
        role = role_by_project.get(project_id) if project_id is not None else None
        access_role = role.value if role is not None else None
        source_kind, source_ref = source_by_container[info.id]
        if not source_kind or not source_ref:
            enriched.append(info.model_copy(update={"access_role": access_role}))
            continue
        display_ref = source_ref
        if source_kind == "dockerfile_template" and source_ref_looks_like_uuid(
            source_ref
        ):
            display_ref = template_names.get(uuid.UUID(source_ref), source_ref)
        enriched.append(
            info.model_copy(
                update={
                    "source_kind": source_kind,
                    "source_label": display_ref,
                    "access_role": access_role,
                }
            )
        )
    return enriched


async def _list_user_containers(
    orchestrator: ContainerOrchestrator,
    session: AsyncSession,
    user: User,
    *,
    container_status: ContainerStatus | None,
    project_ids: set[uuid.UUID],
) -> list[ContainerInfo]:
    return await orchestrator.list(
        status=container_status,
        project_ids=project_ids,
        user_id=user.id,
    )


@router.get("/", response_model=list[ContainerInfo])
async def list_containers(
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    container_status: Annotated[
        ContainerStatus | None,
        Query(alias="status", description="Filter by container status"),
    ] = None,
    # ponytail: default limit = max page so the un-paginated UI still gets every container
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ContainerInfo]:
    """List containers in projects the caller belongs to, optionally filtered by status."""
    project_ids = await list_accessible_project_ids(session, current_user.id)
    containers = await _list_user_containers(
        orchestrator,
        session,
        current_user,
        container_status=container_status,
        project_ids=project_ids,
    )
    page = containers[offset : offset + limit]
    return await _enrich_container_source_labels(
        session, current_user, page, project_ids
    )


@router.get("/image/availability", response_model=ImageAvailabilityResponse)
async def image_availability(
    ref: Annotated[
        str, Query(min_length=1, max_length=2048, description="Docker image reference.")
    ],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> ImageAvailabilityResponse:
    """
    Determine whether the given Docker image reference or Git source is available.

    Parameters:
        ref (str): A Docker image reference or a Git clone URL.

    Returns:
        ImageAvailabilityResponse: For Git clone URLs, `available` is `true` and `checked` is `false`. For image references, `checked` is `true` and `available` is `true` when the image manifest or local image is found. If the image does not exist, `available` is `false`, `can_attempt_deploy` is `false`, and `detail`/`error_code` contain registry error information. If access to the registry is denied, `available` is `false`, `can_attempt_deploy` is `true`, and `detail`/`error_code` contain registry error information.
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
    return ImageAvailabilityResponse(
        ref=source, available=True, checked=True, detail=None
    )


@router.get("/deploy-sources", response_model=DeploySourcesResponse)
async def deploy_source_suggestions(
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str, Query(max_length=512)] = "",
    limit: Annotated[int, Query(ge=1, le=40)] = 22,
) -> DeploySourcesResponse:
    """
    Provide unified autocomplete suggestions for registry images, GitHub repositories, and user Dockerfile templates.

    Parameters:
        q (str): Search query to match suggestions; empty string returns broad suggestions.
        limit (int): Maximum number of suggestions to return (1–40).

    Returns:
        DeploySourcesResponse: Aggregated suggestion list combining registry images, GitHub repositories, and the current user's Dockerfile templates.
    """
    return await collect_deploy_source_suggestions(
        session=session,
        user=current_user,
        orchestrator=orchestrator,
        query=q,
        limit=limit,
    )


@router.get("/image/suggestions", response_model=ImageSuggestionsResponse)
async def image_suggestions(
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    _current_user: Annotated[User, Depends(get_current_user)],
    q: Annotated[str, Query(max_length=128)] = "",
    limit: Annotated[int, Query(ge=1, le=40)] = 20,
) -> ImageSuggestionsResponse:
    """
    Return image autocomplete suggestions combining local engine tags and Docker Hub results.

    Parameters:
        q (str): Query string to match image refs; leading/trailing whitespace is ignored.
        limit (int): Maximum number of suggestions to return.

    Returns:
        ImageSuggestionsResponse: Suggestions limited to `limit`, merged from local engine tags and Docker Hub (sorted/merged by relevance and pull count). If the orchestrator is unreachable, local tags are treated as empty and only Docker Hub results (when `q` is non-empty) are used.
    """
    stripped = q.strip()
    try:
        local_tags = await orchestrator.list_images()
    except ProviderConnectionError:
        local_tags = []
    hub_page = max(limit * 2, 25)
    hub_rows = (
        await fetch_docker_hub_suggestions(stripped, page_size=hub_page)
        if stripped
        else []
    )
    merged = merge_image_suggestions(
        query=stripped,
        limit=limit,
        local_tags=local_tags,
        hub_rows=hub_rows,
    )
    return ImageSuggestionsResponse(
        suggestions=[
            ImageSuggestion(
                ref=item.ref,
                pull_count=item.pull_count,
                source=item.source,
            )
            for item in merged
        ],
    )


@router.post("/deploy", response_model=ContainerDeployResponse)
async def deploy(
    config: DeployConfig,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContainerDeployResponse:
    """Create and start a container from configuration."""
    project_id = await _resolve_deploy_project_id_for_config(
        session, current_user, config.project_id
    )
    await enforce_team_storage_capacity(session, orchestrator, project_id)
    config = _apply_deploy_labels(
        config,
        owner_id=str(current_user.id),
        project_id=project_id,
    )
    config = await apply_public_route_to_deploy_config(config, traffic_router)
    info, route_wired, public_url = await _deploy_and_maybe_wire_route(
        orchestrator, traffic_router, config
    )
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="container.deploy",
        target_type="container",
        target_id=info.id,
        details={"image": config.image, "container_name": info.name},
    )
    await session.commit()
    return ContainerDeployResponse(
        container=info,
        route_wired=route_wired,
        public_url=public_url,
    )


@router.post("/volume-uploads", response_model=VolumeUploadResponse)
async def upload_volume_folder(
    files: Annotated[list[UploadFile], File(...)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> VolumeUploadResponse:
    """Upload a local folder for read-only volume mounts (max 100 MB per folder)."""
    if not files:
        raise InvalidVolumeUploadPathError(
            "Select a folder that contains at least one file."
        )

    per_folder_limit = volume_upload_max_bytes()
    user_quota = volume_upload_user_quota_bytes()
    current_usage = user_uploads_total_bytes(current_user.id)

    payloads: list[tuple[str, bytes]] = []
    total_bytes = 0
    for upload in files:
        relative_path = upload.filename or ""
        # Only read content if early size check passes\
        if upload.size is not None and total_bytes + upload.size > per_folder_limit:
            limit_megabytes = per_folder_limit // (1024 * 1024)
            raise VolumeUploadTooLargeError(
                f"Folder exceeds the {limit_megabytes} MB upload limit."
            )
        content = await upload.read()
        total_bytes += len(content)
        if total_bytes > per_folder_limit:
            limit_megabytes = per_folder_limit // (1024 * 1024)
            raise VolumeUploadTooLargeError(
                f"Folder exceeds the {limit_megabytes} MB upload limit."
            )
        if current_usage + total_bytes > user_quota:
            limit_megabytes = user_quota // (1024 * 1024)
            raise VolumeUploadQuotaExceededError(
                f"Upload would exceed your {limit_megabytes} MB volume storage quota. "
                "Use a smaller folder or remove unused uploads."
            )
        payloads.append((relative_path, content))

    personal_project_id = await get_personal_project_id(session, current_user)
    personal_project = await session.get(Project, personal_project_id)
    team_quota = (
        effective_quota_bytes(personal_project)
        if personal_project is not None
        else None
    )
    if team_quota is not None:
        disk_bytes, uploads_bytes = await team_storage_usage(
            session, orchestrator, personal_project_id
        )
        used_bytes = disk_bytes + uploads_bytes
        if used_bytes + total_bytes > team_quota:
            raise TeamStorageQuotaExceededError(
                f"Upload would exceed the team's {format_gib(team_quota)} "
                f"storage quota ({format_gib(used_bytes)} used). "
                "Use a smaller folder or remove unused uploads."
            )

    upload_id, folder_name, saved_bytes, file_count = save_volume_upload(
        current_user.id,
        payloads,
    )
    return VolumeUploadResponse(
        upload_id=upload_id,
        folder_name=folder_name,
        total_bytes=saved_bytes,
        file_count=file_count,
        max_bytes=per_folder_limit,
        user_quota_bytes=user_quota,
        user_used_bytes=user_uploads_total_bytes(current_user.id),
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
    """
    Deploy a container by pulling or building an image from the user's specified source and return the deployment result.

    Depending on body.source_kind this will:
    - "image": use the provided image reference (pull if needed) and deploy it.
    - "dockerfile_template": build an ephemeral image from the user's saved Dockerfile template, then deploy it.
    - "git": clone the Git source (using the caller's GitHub token for GitHub HTTPS URLs when available), build an image from the source, then deploy it.
    When a public route is requested, route-related fields are adjusted and a Traefik route may be registered; private-repo clone failures on GitHub produce a CloneError with guidance to connect GitHub when applicable.

    Returns:
        RunFromSourceResponse: deployment result containing the created container info, the source kind, built/pulled image tag, whether a route was wired, and an optional public URL.
    """
    source_kind = body.source_kind
    if source_kind is None:
        raise ValueError("source_kind must be set after request validation.")

    project_id = await _resolve_deploy_project_id(session, current_user, body)
    await enforce_team_storage_capacity(session, orchestrator, project_id)
    resolved_volumes = _resolve_deploy_volumes(current_user.id, body.volumes)

    if source_kind == "image":
        image_ref = (body.image_ref or "").strip()
        cfg = _deploy_config_for_image(
            image=image_ref,
            container_name=body.container_name,
            host_port=body.host_port,
            container_port=body.container_port,
            env_vars=body.env_vars,
            command=body.command,
            volumes=resolved_volumes,
            cpu_limit=body.cpu_limit,
            memory_limit=body.memory_limit,
        ).model_copy(update=_route_updates_from_run_body(body))
        cfg = with_deploy_source_labels(cfg, source_kind="image", source_ref=image_ref)
        cfg = _apply_deploy_labels(
            cfg, owner_id=str(current_user.id), project_id=project_id
        )
        cfg = await apply_public_route_to_deploy_config(cfg, traffic_router)
        info, route_wired, public_url = await _deploy_and_maybe_wire_route(
            orchestrator, traffic_router, cfg
        )
        await _persist_run_deployment(
            session,
            current_user,
            body,
            info,
            project_id=project_id,
            source_kind="image",
            source_ref=image_ref,
            image_tag=image_ref,
            dockerfile_snapshot=None,
            public_url=public_url,
        )
        saved_policy, scaling_policy_warning = await _persist_scaling_policy(
            session, info.name, body
        )
        await emit_audit_log(
            session,
            user_id=current_user.id,
            action="container.deploy",
            target_type="container",
            target_id=info.id,
            details={
                "source_kind": "image",
                "source_ref": image_ref,
            },
        )
        await session.commit()
        return RunFromSourceResponse(
            container=info,
            kind="image",
            image=image_ref,
            route_wired=route_wired,
            public_url=public_url,
            scaling_policy=saved_policy,
            scaling_policy_warning=scaling_policy_warning,
        )

    if source_kind == "dockerfile_template":
        template_id = body.dockerfile_template_id
        if template_id is None:
            raise ValueError("dockerfile_template_id is required.")
        template = await user_library.get_dockerfile_template(
            session, current_user.id, template_id
        )
        tag = f"vela/templatebuild:{uuid.uuid4().hex[:12]}"
        build_result = await image_builder.build_from_dockerfile_template(
            template.contents,
            tag=tag,
        )
        cfg = _deploy_config_for_image(
            image=build_result.image_tag,
            container_name=body.container_name,
            host_port=body.host_port,
            container_port=body.container_port,
            env_vars=body.env_vars,
            command=body.command,
            volumes=resolved_volumes,
            cpu_limit=body.cpu_limit,
            memory_limit=body.memory_limit,
        ).model_copy(
            update={
                "restart_policy": RestartPolicy.UNLESS_STOPPED,
                **_route_updates_from_run_body(body),
            }
        )
        cfg = with_deploy_source_labels(
            cfg,
            source_kind="dockerfile_template",
            source_ref=template.name,
        )
        cfg = _apply_deploy_labels(
            cfg, owner_id=str(current_user.id), project_id=project_id
        )
        cfg = await apply_public_route_to_deploy_config(cfg, traffic_router)
        info, route_wired, public_url = await _deploy_and_maybe_wire_route(
            orchestrator, traffic_router, cfg
        )
        await _persist_run_deployment(
            session,
            current_user,
            body,
            info,
            project_id=project_id,
            source_kind="dockerfile_template",
            source_ref=template.name,
            image_tag=build_result.image_tag,
            dockerfile_snapshot=build_result.dockerfile_snapshot or template.contents,
            public_url=public_url,
        )
        saved_policy, scaling_policy_warning = await _persist_scaling_policy(
            session, info.name, body
        )
        await emit_audit_log(
            session,
            user_id=current_user.id,
            action="container.deploy",
            target_type="container",
            target_id=info.id,
            details={
                "source_kind": "dockerfile_template",
                "source_ref": template.name,
            },
        )
        await session.commit()
        return RunFromSourceResponse(
            container=info,
            kind="dockerfile_template",
            image=build_result.image_tag,
            route_wired=route_wired,
            public_url=public_url,
            scaling_policy=saved_policy,
            scaling_policy_warning=scaling_policy_warning,
        )

    git_url = (body.git_url or "").strip()
    access_token = await _github_token_for_url(session, current_user, git_url)
    tag = f"vela/gitbuild:{uuid.uuid4().hex[:12]}"
    try:
        build_result = await image_builder.build_from_source(
            ProjectSource(git_url=git_url, branch=body.git_branch),
            tag=tag,
            access_token=access_token,
            override=body.build_override,
        )
    except CloneError as exc:
        if (
            access_token is None
            and _is_github_https_url(git_url)
            and _looks_like_auth_failure(str(exc))
        ):
            raise CloneError(
                git_url,
                "Repository looks private. Connect GitHub in Settings to deploy private repos.",
            ) from exc
        raise

    cfg = _deploy_config_for_image(
        image=build_result.image_tag,
        container_name=body.container_name,
        host_port=body.host_port,
        container_port=body.container_port,
        env_vars=body.env_vars,
        command=body.command,
        volumes=resolved_volumes,
        cpu_limit=body.cpu_limit,
        memory_limit=body.memory_limit,
    ).model_copy(
        update={
            "restart_policy": RestartPolicy.UNLESS_STOPPED,
            **_route_updates_from_run_body(body),
        }
    )
    cfg = with_deploy_source_labels(cfg, source_kind="git", source_ref=git_url)
    cfg = _apply_deploy_labels(
        cfg, owner_id=str(current_user.id), project_id=project_id
    )
    cfg = await apply_public_route_to_deploy_config(cfg, traffic_router)
    info, route_wired, public_url = await _deploy_and_maybe_wire_route(
        orchestrator, traffic_router, cfg
    )
    await _persist_run_deployment(
        session,
        current_user,
        body,
        info,
        project_id=project_id,
        source_kind="git",
        source_ref=git_url,
        image_tag=build_result.image_tag,
        dockerfile_snapshot=build_result.dockerfile_snapshot,
        public_url=public_url,
    )
    saved_policy, scaling_policy_warning = await _persist_scaling_policy(
        session, info.name, body
    )
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="container.deploy",
        target_type="container",
        target_id=info.id,
        details={
            "source_kind": "git",
            "source_ref": _sanitize_url_for_audit(git_url),
        },
    )
    await session.commit()
    return RunFromSourceResponse(
        container=info,
        kind="git",
        image=build_result.image_tag,
        route_wired=route_wired,
        public_url=public_url,
        scaling_policy=saved_policy,
        scaling_policy_warning=scaling_policy_warning,
    )


@router.get("/{container_id}", response_model=ContainerInfo)
async def get_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContainerInfo:
    """Return detailed information about a single managed container."""
    return await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )


@router.post("/{container_id}/start", response_model=ContainerInfo)
async def start_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContainerInfo:
    """Start a stopped container."""
    access_info = await require_container_access(
        session, orchestrator, current_user, container_id, action="write"
    )
    updated = await orchestrator.start(container_id)
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="container.start",
        target_type="container",
        target_id=container_id,
    )
    await session.commit()
    return updated.model_copy(update={"access_role": access_info.access_role})


@router.post("/{container_id}/stop", response_model=ContainerInfo)
async def stop_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    timeout: int = 10,
) -> ContainerInfo:
    """Gracefully stop a running container."""
    access_info = await require_container_access(
        session, orchestrator, current_user, container_id, action="write"
    )
    updated = await orchestrator.stop(container_id, timeout=timeout)
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="container.stop",
        target_type="container",
        target_id=container_id,
        details={"timeout": timeout},
    )
    await session.commit()
    return updated.model_copy(update={"access_role": access_info.access_role})


@router.post("/{container_id}/restart", response_model=ContainerInfo)
async def restart_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    timeout: int = 10,
) -> ContainerInfo:
    """Restart a container."""
    access_info = await require_container_access(
        session, orchestrator, current_user, container_id, action="write"
    )
    updated = await orchestrator.restart(container_id, timeout=timeout)
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="container.restart",
        target_type="container",
        target_id=container_id,
        details={"timeout": timeout},
    )
    await session.commit()
    return updated.model_copy(update={"access_role": access_info.access_role})


@router.delete("/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_container(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    force: bool = False,
) -> Response:
    """Remove a container and drop any Traefik route keyed by its name."""
    info = await require_container_access(
        session, orchestrator, current_user, container_id, action="write"
    )
    await remove_route_for_container_name(
        traffic_router=traffic_router,
        container_name=info.name,
    )
    await orchestrator.remove(container_id, force=force)
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="container.remove",
        target_type="container",
        target_id=container_id,
        details={"force": force},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{container_id}/logs", response_model=dict[str, str])
async def container_logs(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    tail: Annotated[int, Query(ge=1, le=_MAX_LOG_TAIL_LINES)] = 100,
) -> dict[str, str]:
    """Return recent log lines for a container."""
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )
    text = await orchestrator.logs(container_id, tail=tail)
    return {"logs": text}


@router.websocket("/{container_id}/logs/stream")
async def container_logs_stream(
    websocket: WebSocket,
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Stream container logs over WebSocket (binary frames). Authenticate with ``access_token`` query param."""
    await websocket.accept()
    token = websocket.query_params.get("access_token")
    tail_raw = websocket.query_params.get("tail", "200")
    try:
        tail_parsed = int(tail_raw)
    except ValueError:
        tail_parsed = 200
    tail_parsed = max(1, min(tail_parsed, _MAX_LOG_TAIL_LINES))
    follow_logs = (
        websocket.query_params.get("follow", "true").strip().lower() != "false"
    )

    try:
        if not token:
            raise NotAuthenticatedError()
        claims = decode_access_token(token)
        user = await get_user_by_id(session, claims.user_id)
        if user is None:
            raise NotAuthenticatedError()
    except NotAuthenticatedError:
        await websocket.close(code=1008)
        return
    try:
        await require_container_access(
            session, orchestrator, user, container_id, action="read"
        )
    except (ContainerNotFoundError, ProjectAccessDeniedError):
        await websocket.close(code=1008)
        return

    try:
        async for chunk in orchestrator.stream_logs(
            container_id,
            tail=tail_parsed,
            follow=follow_logs,
        ):
            await websocket.send_bytes(chunk)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@router.websocket("/{container_id}/exec/ws")
async def container_exec_ws(
    websocket: WebSocket,
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Bidirectional exec terminal over WebSocket. Authenticate with ``access_token`` query param."""
    token = websocket.query_params.get("access_token")

    try:
        if not token:
            raise NotAuthenticatedError()
        claims = decode_access_token(token)
        user = await get_user_by_id(session, claims.user_id)
        if user is None:
            raise NotAuthenticatedError()
    except NotAuthenticatedError:
        await websocket.close(code=1008, reason="Unauthorized")
        return

    try:
        await require_container_access(
            session, orchestrator, user, container_id, action="write"
        )
    except (ContainerNotFoundError, ProjectAccessDeniedError):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await emit_audit_log(
        session,
        user_id=user.id,
        action="container.exec",
        target_type="container",
        target_id=container_id,
    )
    await session.commit()
    await session.close()

    try:
        await websocket.accept()
    except WebSocketDisconnect:
        return

    try:
        await asyncio.wait_for(
            _exec_semaphore.acquire(), timeout=_EXEC_SEMAPHORE_ACQUIRE_TIMEOUT
        )
    except TimeoutError:
        await websocket.close(
            code=1013, reason="Too many concurrent terminals, try again shortly"
        )
        return

    exec_close_fn: Callable[[], None] | None = None
    try:
        cols, rows = 80, 24
        pending_init: str | None = None
        try:
            init_raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            try:
                init_msg = json.loads(init_raw)
                if isinstance(init_msg, dict) and ("cols" in init_msg or "rows" in init_msg):
                    cols = int(init_msg.get("cols", 80))
                    rows = int(init_msg.get("rows", 24))
                else:
                    pending_init = init_raw
            except (json.JSONDecodeError, ValueError, TypeError):
                pending_init = init_raw
        except asyncio.TimeoutError:
            pass

        try:
            stdout_iter, stdin_write, exec_close_fn, exec_id = await orchestrator.stream_exec(
                container_id, cols=cols, rows=rows
            )
        except Exception as exc:
            logger.warning("exec start failed for %s: %s", container_id, exc)
            try:
                await websocket.send_text(_EXEC_START_FAILURE_MESSAGE)
                await websocket.close(code=1011)
            except Exception:
                pass
            return

        if pending_init is not None:
            await asyncio.to_thread(stdin_write, pending_init.encode("utf-8"))

        async def _forward_to_client() -> None:
            try:
                async for chunk in stdout_iter:
                    await websocket.send_bytes(chunk)
            except WebSocketDisconnect:
                pass
            except Exception:
                logger.warning("exec forward error for %s", container_id)

        async def _forward_to_container() -> None:
            try:
                while True:
                    msg = await websocket.receive_text()
                    resize = _parse_resize_message(msg)
                    if resize is not None:
                        new_cols, new_rows = resize
                        await asyncio.to_thread(
                            orchestrator.resize_exec,
                            container_id, exec_id, new_cols, new_rows,
                        )
                        continue
                    await asyncio.to_thread(stdin_write, msg.encode("utf-8"))
            except WebSocketDisconnect:
                pass
            except Exception:
                logger.warning("exec input error for %s", container_id)

        task_client = asyncio.create_task(_forward_to_client())
        task_container = asyncio.create_task(_forward_to_container())
        try:
            _, pending = await asyncio.wait_for(
                asyncio.wait(
                    {task_client, task_container},
                    return_when=asyncio.FIRST_COMPLETED,
                ),
                timeout=_exec_max_session_seconds(),
            )
        except TimeoutError:
            pending = {task_client, task_container}
            try:
                await asyncio.wait_for(
                    websocket.send_text("[session expired]"), timeout=5.0
                )
                await websocket.close(code=1000, reason="Session timeout")
            except Exception:
                pass
        for t in pending:
            t.cancel()
            with suppress(asyncio.CancelledError):
                await t
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.error("exec session error for %s", container_id)
    finally:
        if exec_close_fn is not None:
            exec_close_fn()
        _exec_semaphore.release()


@router.get("/{container_id}/stats", response_model=ContainerStats)
async def container_stats(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContainerStats:
    """Return resource usage snapshot for a container."""
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )
    return await orchestrator.get_stats(container_id)


@router.get("/{container_id}/health", response_model=HealthResult)
async def container_health(
    container_id: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HealthResult:
    """Return latest health check result for a container."""
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )
    return await orchestrator.get_health(container_id)
