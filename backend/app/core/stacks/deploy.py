"""Coordinated deployment of stack services onto a shared Docker network."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import user_library
from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.containers.docker_orchestrator import (
    VELA_OWNER_LABEL,
    VELA_PROJECT_LABEL,
    VELA_SOURCE_KIND_LABEL,
    VELA_SOURCE_REF_LABEL,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.containers.volume_uploads import resolve_volume_upload_path
from app.core.enums import RestartPolicy
from app.core.exceptions import CloneError, NeedsBuildOverrideError
from app.core.models import (
    BuildOverride,
    ContainerInfo,
    DeployConfig,
    ProjectSource,
    VolumeMount,
)
from app.core.traffic.traffic_router import TrafficRouter
from app.core.url_display import sanitize_url_for_display
from app.db.models import DeploymentRecord, Stack, StackService, User


def _build_override_from_service(service: StackService) -> BuildOverride | None:
    raw = service.build_override
    if not raw:
        return None
    return BuildOverride.model_validate(raw)


async def deploy_stack(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    image_builder: DefaultImageBuilder,
    stack: Stack,
    user: User,
    child_stacks: list[Stack],
) -> dict[str, object]:
    """Deploy all services in a stack onto a shared network.

    On failure, rolls back all started containers and removes the network.

    Returns:
        Dict with 'containers', 'route_wired', 'public_url' per service, and 'error' if failed.
    """
    from app.core.stacks.repository import resolve_composition

    services = resolve_composition(stack, child_stacks)
    if not services:
        return {"error": "Stack has no services to deploy."}

    deployed_containers: list[ContainerInfo] = []

    try:
        await orchestrator.create_network(stack.network_name)

        for service in services:
            container_name = f"{stack.name}_{service.service_name}"
            image_tag = await _resolve_service_image(
                session,
                user,
                image_builder,
                service,
            )
            config = _build_deploy_config(
                stack,
                service,
                container_name,
                user,
                image_tag=image_tag,
            )

            info = await orchestrator.deploy(config)
            deployed_containers.append(info)

            if service.public_route:
                from app.api.route_wiring import register_route_for_deployed_container

                try:
                    await register_route_for_deployed_container(
                        traffic_router=traffic_router,
                        container_info=info,
                        route_host=info.access_url
                        or f"{service.service_name}.{stack.network_name}.local",
                        path_prefix="/",
                        backend_port=service.container_port,
                        tls_enabled=False,
                    )
                except Exception:
                    pass

            await _persist_deployment(
                session,
                user,
                stack,
                service,
                info,
                image_tag=image_tag,
            )

            if service.scaling_policy:
                await _persist_scaling_policy(
                    session, container_name, service.scaling_policy
                )

        await session.commit()
        return {
            "containers": [
                {
                    "service_name": s.service_name,
                    "container_id": c.id,
                    "container_name": c.name,
                }
                for s, c in zip(services, deployed_containers)
            ],
        }

    except Exception as exc:
        for container in deployed_containers:
            try:
                await orchestrator.stop(container.id, timeout=5)
                await orchestrator.remove(container.id, force=True)
            except Exception:
                pass

        try:
            await orchestrator.remove_network(stack.network_name)
        except Exception:
            pass

        failed_service = None
        if len(deployed_containers) < len(services):
            failed_service = services[len(deployed_containers)].service_name

        if isinstance(exc, NeedsBuildOverrideError):
            if failed_service:
                raise NeedsBuildOverrideError(
                    f"Deploy failed on service '{failed_service}': {exc}"
                ) from exc
            raise

        return {
            "error": str(exc),
            "failed_service": failed_service,
            "containers": [],
        }


async def _resolve_service_image(
    session: AsyncSession,
    user: User,
    image_builder: DefaultImageBuilder,
    service: StackService,
) -> str:
    """Return the Docker image tag to deploy for a stack service."""
    match service.source_kind:
        case "image":
            return service.source_ref.strip()
        case "dockerfile_template":
            template = await user_library.resolve_dockerfile_template(
                session,
                user.id,
                service.source_ref,
            )
            tag = f"vela/templatebuild:{uuid.uuid4().hex[:12]}"
            build_result = await image_builder.build_from_dockerfile_template(
                template.contents,
                tag=tag,
            )
            return build_result.image_tag
        case "git":
            from app.core.deploy.github_auth import (
                github_token_for_url,
                is_github_https_url,
                looks_like_auth_failure,
            )

            git_url = service.source_ref.strip()
            branch = (service.git_branch or "main").strip() or "main"
            access_token = await github_token_for_url(session, user, git_url)
            tag = f"vela/gitbuild:{uuid.uuid4().hex[:12]}"
            override = _build_override_from_service(service)
            try:
                build_result = await image_builder.build_from_source(
                    ProjectSource(git_url=git_url, branch=branch),
                    tag=tag,
                    access_token=access_token,
                    override=override,
                )
            except CloneError as exc:
                if (
                    access_token is None
                    and is_github_https_url(git_url)
                    and looks_like_auth_failure(str(exc))
                ):
                    raise CloneError(
                        git_url,
                        "Repository looks private. Connect GitHub in Settings to deploy private repos.",
                    ) from exc
                raise
            return build_result.image_tag
        case _:
            raise ValueError(f"Unsupported source_kind: {service.source_kind}")


def _build_deploy_config(
    stack: Stack,
    service: StackService,
    container_name: str,
    user: User,
    *,
    image_tag: str,
) -> DeployConfig:
    """Build a DeployConfig for a stack service."""
    volumes = []
    for mount in service.volumes or []:
        upload_id = mount.get("upload_id")
        target = mount.get("target", "")
        if upload_id and target:
            source = str(resolve_volume_upload_path(user.id, uuid.UUID(upload_id)))
            volumes.append(VolumeMount(source=source, target=target))

    restart_policy = (
        RestartPolicy.UNLESS_STOPPED
        if service.source_kind in {"git", "dockerfile_template"}
        else RestartPolicy.NEVER
    )

    return DeployConfig(
        image=image_tag,
        name=container_name,
        env_vars=dict(service.env_vars),
        volumes=volumes,
        container_listen_port=service.container_port,
        command=service.command,
        network=stack.network_name,
        restart_policy=restart_policy,
        labels={
            "vela.stack_id": str(stack.id),
            "vela.service_name": service.service_name,
            "vela.network": stack.network_name,
            VELA_OWNER_LABEL: str(user.id),
            VELA_PROJECT_LABEL: str(stack.project_id),
            VELA_SOURCE_KIND_LABEL: service.source_kind,
            VELA_SOURCE_REF_LABEL: sanitize_url_for_display(service.source_ref),
        },
        public_route=service.public_route,
    )


async def _persist_scaling_policy(
    session: AsyncSession,
    container_name: str,
    policy_dict: dict,
) -> None:
    """Persist an auto-scaling policy for a stack service container."""
    from app.core.models import ScalingPolicyConfig
    from app.core.scaling.policy_repository import upsert_policy

    try:
        config = ScalingPolicyConfig(**policy_dict)
        await upsert_policy(session, container_name, config)
    except Exception:
        pass


async def _persist_deployment(
    session: AsyncSession,
    user: User,
    stack: Stack,
    service: StackService,
    container_info: ContainerInfo,
    *,
    image_tag: str,
) -> None:
    """Persist a DeploymentRecord for a stack service deployment."""
    record = DeploymentRecord(
        user_id=user.id,
        project_id=stack.project_id,
        container_id=container_info.id,
        container_name=container_info.name,
        source_kind=service.source_kind,
        source_ref=sanitize_url_for_display(service.source_ref),
        image_tag=image_tag,
        container_port=service.container_port,
        env_vars={k: "<REDACTED>" for k in service.env_vars},
        command=service.command,
        stack_id=stack.id,
    )
    session.add(record)
