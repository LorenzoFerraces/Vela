"""Coordinated deployment of stack services onto a shared Docker network."""

from __future__ import annotations

from collections.abc import Callable
import logging
import uuid

from sqlalchemy import select
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

logger = logging.getLogger(__name__)


def _container_dns_name(stack: Stack, service: StackService) -> str:
    return f"{stack.name}_{service.service_name}"


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
    *,
    on_phase: Callable[[str, str | None], None] | None = None,
    on_service_state: Callable[[str, str], None] | None = None,
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

    # Plain copies up front: a persist-retry rollback can expire the ORM
    # objects, and an async session cannot lazy-load an expired attribute
    # outside a greenlet.
    service_names = [service.service_name for service in services]
    network_name = stack.network_name

    deployed_containers: list[ContainerInfo] = []
    deployed_records: list[DeploymentRecord] = []

    try:
        if on_phase is not None:
            on_phase("deploying", None)

        await orchestrator.create_network(network_name)

        for service in services:
            container_name = _container_dns_name(stack, service)
            if on_service_state is not None:
                on_service_state(service.service_name, "building")
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

            if on_service_state is not None:
                on_service_state(service.service_name, "starting")
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

            deployed_records.append(
                await _persist_deployment(
                    session,
                    user,
                    stack,
                    service,
                    info,
                    image_tag=image_tag,
                )
            )

            if service.scaling_policy:
                await _persist_scaling_policy(
                    session, container_name, service.scaling_policy
                )

            if on_service_state is not None:
                on_service_state(service.service_name, "running")

        await _commit_deployment_records(session, deployed_records)
        return {
            "containers": [
                {
                    "service_name": name,
                    "container_id": c.id,
                    "container_name": c.name,
                }
                for name, c in zip(service_names, deployed_containers)
            ],
        }

    except Exception as exc:
        if on_phase is not None:
            on_phase("rolling_back", None)

        for container in deployed_containers:
            try:
                await orchestrator.stop(container.id, timeout=5)
                await orchestrator.remove(container.id, force=True)
            except Exception:
                pass

        try:
            await orchestrator.remove_network(network_name)
        except Exception:
            pass

        failed_service = None
        if len(deployed_containers) < len(services):
            failed_service = service_names[len(deployed_containers)]

        if failed_service is not None and on_service_state is not None:
            on_service_state(failed_service, "failed")

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
        network_aliases=[service.service_name],
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
) -> DeploymentRecord:
    """Stage a DeploymentRecord for a stack service deployment."""
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
    return record


def _deployment_record_values(record: DeploymentRecord) -> dict[str, object]:
    """Plain copy of a staged record's values, taken while its attributes
    are still loaded. Retries build fresh instances from this snapshot
    instead of re-reading ORM attributes (a session rollback expires them,
    and an async session cannot lazy-load an expired attribute outside a
    greenlet). Fresh instances also INSERT a new row where re-adding the
    wiped record's known identity would not."""
    return {
        "user_id": record.user_id,
        "project_id": record.project_id,
        "container_id": record.container_id,
        "container_name": record.container_name,
        "source_kind": record.source_kind,
        "source_ref": record.source_ref,
        "image_tag": record.image_tag,
        "container_port": record.container_port,
        "env_vars": dict(record.env_vars),
        "command": list(record.command) if record.command else None,
        "stack_id": record.stack_id,
    }


async def _commit_deployment_records(
    session: AsyncSession,
    records: list[DeploymentRecord],
) -> None:
    """Commit the staged DeploymentRecords, retrying a bounded number of
    times and verifying the rows landed. In tests, a poll request's
    teardown ROLLBACK on the shared in-memory connection can wipe the
    pending INSERTs between the worker's flush and commit; the commit then
    succeeds on an empty transaction and the records are silently lost. A
    persist failure must never fail the deploy job."""
    container_ids = [record.container_id for record in records]
    snapshots = [_deployment_record_values(record) for record in records]
    for attempt in range(3):
        pending = [DeploymentRecord(**values) for values in snapshots]
        try:
            for record in pending:
                session.add(record)
            await session.commit()
            landed = await session.execute(
                select(DeploymentRecord.container_id).where(
                    DeploymentRecord.container_id.in_(container_ids)
                )
            )
            if len(landed.scalars().all()) == len(container_ids):
                return
            logger.warning(
                "Stack deploy persist attempt %d/3: records missing after commit for containers %s",
                attempt + 1,
                container_ids,
            )
        except Exception:
            logger.exception(
                "Stack deploy persist attempt %d/3 failed for containers %s",
                attempt + 1,
                container_ids,
            )
        try:
            # Reset session state before retrying. expunge_all never raises
            # for objects a failed commit already detached, unlike
            # per-record expunge. A persist failure must never fail the
            # deploy job.
            session.expunge_all()
            await session.rollback()
        except Exception:
            logger.exception(
                "Could not reset session before stack deploy persist retry for containers %s",
                container_ids,
            )
    logger.error(
        "Stack deploy persist: records still missing after 3 attempts for containers %s",
        container_ids,
    )
