"""Container orchestration API backed by :class:`~app.core.containers.docker_orchestrator.DockerOrchestrator`."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    WebSocket,
    status,
)
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
from app.core.deploy.deploy_source_display import resolve_deploy_source_label
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
from app.core.projects.access import (
    list_accessible_project_ids,
    membership_role_for_container,
    require_container_access,
)
from app.core.projects.enums import can_write
from app.core.projects.repository import get_personal_project_id, require_membership
from app.core.traffic.public_route_host import (
    apply_public_route_to_deploy_config,
    build_public_url,
    read_public_route_settings,
)
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_LOG_TAIL_LINES = 2000


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


async def _enrich_container_source_labels(
    session: AsyncSession,
    user: User,
    containers: list[ContainerInfo],
) -> list[ContainerInfo]:
    """Fill ``source_label`` and ``access_role`` for listed containers."""
    history_by_container = await latest_source_by_container_ids(
        session,
        user.id,
        [row.id for row in containers],
    )
    enriched: list[ContainerInfo] = []
    for info in containers:
        role = await membership_role_for_container(session, user.id, info)
        access_role = role.value if role is not None else None
        source_kind = info.source_kind or info.labels.get(VELA_SOURCE_KIND_LABEL)
        source_ref = info.source_label or info.labels.get(VELA_SOURCE_REF_LABEL) or ""
        if not source_ref and info.id in history_by_container:
            history_kind, history_ref = history_by_container[info.id]
            source_kind = source_kind or history_kind
            source_ref = history_ref
        if not source_kind or not source_ref:
            enriched.append(info.model_copy(update={"access_role": access_role}))
            continue
        display_ref = await resolve_deploy_source_label(
            session,
            user.id,
            source_kind=source_kind,
            source_ref=source_ref,
        )
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
) -> list[ContainerInfo]:
    project_ids = await list_accessible_project_ids(session, user.id)
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
) -> list[ContainerInfo]:
    """List containers in projects the caller belongs to, optionally filtered by status."""
    containers = await _list_user_containers(
        orchestrator,
        session,
        current_user,
        container_status=container_status,
    )
    return await _enrich_container_source_labels(session, current_user, containers)


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
    q: Annotated[str, Query(max_length=128)] = "",
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
    config = _apply_deploy_labels(
        config,
        owner_id=str(current_user.id),
        project_id=project_id,
    )
    config = await apply_public_route_to_deploy_config(config, traffic_router)
    info, route_wired, public_url = await _deploy_and_maybe_wire_route(
        orchestrator, traffic_router, config
    )
    return ContainerDeployResponse(
        container=info,
        route_wired=route_wired,
        public_url=public_url,
    )


@router.post("/volume-uploads", response_model=VolumeUploadResponse)
async def upload_volume_folder(
    files: Annotated[list[UploadFile], File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
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
