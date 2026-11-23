"""Auto-scaling engine: monitors metrics and adjusts replica count via Docker + Traefik."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.enums import ContainerStatus, ScalingMetric
from app.core.exceptions import (
    ContainerNotFoundError,
    OrchestratorError,
    ProviderConnectionError,
    RouteNotFoundError,
    TeamComputeQuotaExceededError,
)
from app.core.models import ContainerInfo, ContainerStats, DeployConfig
from app.core.monitoring import edge_requests
from app.core.quotas import enforce_team_compute_capacity
from app.core.scaling.policy_repository import (
    ScalingPolicyRuntime,
    list_enabled_policies,
    record_scale_event,
    update_stabilization_state,
)
from app.core.traffic.traffic_models import BackendServer, RouteSpec
from app.core.traffic.traffic_router import NoopTrafficRouter, TrafficRouter

logger = logging.getLogger(__name__)

_LOOP_INTERVAL_SECONDS = 15


async def _stats_or_none(
    orchestrator: ContainerOrchestrator,
    container_name: str,
) -> ContainerStats | None:
    """Read container stats, returning None when the provider is unavailable."""
    try:
        return await orchestrator.get_stats(container_name)
    except (
        ContainerNotFoundError,
        ProviderConnectionError,
        OrchestratorError,
    ) as exc:
        logger.debug("Could not read stats for %s: %s", container_name, exc)
        return None


async def _measure_metric(
    orchestrator: ContainerOrchestrator,
    container_name: str,
    metric: ScalingMetric,
    traffic_router: TrafficRouter,
) -> float | None:
    """Return the current metric value for ``container_name``, or None on failure."""
    if metric is ScalingMetric.REQUESTS_PER_SECOND and not isinstance(
        traffic_router, NoopTrafficRouter
    ):
        signal = edge_requests.get_edge_request_rates()
        # ponytail: an empty map means logs rotated/lagged, not zero traffic — fail closed.
        if not signal.available or not signal.rates_by_host:
            return None
        try:
            route = await traffic_router.get_route(container_name)
        except RouteNotFoundError:
            return None
        # A routed host absent from a flowing signal is genuinely idle (scale-down case).
        return signal.rates_by_host.get(route.host, 0.0)
    stats = await _stats_or_none(orchestrator, container_name)
    if stats is None:
        return None
    # ponytail: noop router has no request signal; CPU is an explicit, documented proxy.
    return float(stats.cpu_percent)


def _is_in_cooldown(runtime: ScalingPolicyRuntime) -> bool:
    policy = runtime.policy
    if policy.last_scaled_at is None:
        return False
    now = datetime.now(UTC)
    elapsed = (now - policy.last_scaled_at).total_seconds()
    return elapsed < policy.cooldown_seconds


def _stabilization_elapsed(
    condition_since: datetime | None,
    stabilization_seconds: int,
    now: datetime,
) -> bool:
    if condition_since is None:
        return False
    return (now - condition_since).total_seconds() >= stabilization_seconds


async def _build_route_spec_for_service(
    traffic_router: TrafficRouter,
    base_name: str,
) -> RouteSpec | None:
    """Return the current RouteSpec for the base container, or None if no route exists."""
    try:
        existing = await traffic_router.get_route(base_name)
    except RouteNotFoundError:
        return None
    return RouteSpec(
        route_id=existing.route_id,
        host=existing.host,
        path_prefix=existing.path_prefix,
        backend_servers=list(existing.backend_servers),
        tls_enabled=existing.tls_enabled,
        entrypoints=list(existing.entrypoints),
    )


async def _collect_replica_configs(
    orchestrator: ContainerOrchestrator,
    base_name: str,
) -> list[tuple[str, int]]:
    """Return ``(container_name, index)`` pairs for existing replicas, sorted by index."""
    replicas = await orchestrator.list_replicas(base_name)
    result: list[tuple[str, int]] = []
    for replica in replicas:
        name = replica.name
        if name.startswith(f"{base_name}-r"):
            suffix = name[len(f"{base_name}-r") :]
            if suffix.isdigit():
                result.append((name, int(suffix)))
    return sorted(result, key=lambda pair: pair[1])


async def _upsert_route_with_replicas(
    traffic_router: TrafficRouter,
    base_spec: RouteSpec,
    base_name: str,
    base_port: int,
    replica_names: list[str],
) -> None:
    """Rebuild the Traefik route so it points to the base container plus all live replicas."""
    servers = [BackendServer(host=base_name, port=base_port)]
    for replica_name in replica_names:
        servers.append(BackendServer(host=replica_name, port=base_port))
    updated_spec = base_spec.model_copy(update={"backend_servers": servers})
    await traffic_router.upsert_route(updated_spec)


def build_replica_config(base: DeployConfig, index: int) -> DeployConfig:
    """Derive a replica config from the stored deploy config (not lossy inspection data)."""
    return base.model_copy(update={
        "name": f"{base.name}-r{index}",
        "ports": [],
        "route_host": None,
        "public_route": False,
    })


async def _base_container_info(
    orchestrator: ContainerOrchestrator, base_name: str
) -> ContainerInfo | None:
    """Resolve a policy's container name to the live container and its Docker id."""
    return next(
        (info for info in await orchestrator.list() if info.name == base_name),
        None,
    )


async def _scale_up(
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    base_name: str,
    base_port: int,
    base_spec: RouteSpec,
    current_replica_count: int,
    base_config: DeployConfig,
    session: AsyncSession,
) -> None:
    """Add one replica and register it with Traefik."""
    next_index = current_replica_count + 1
    if base_config.project_id is not None:
        try:
            await enforce_team_compute_capacity(
                session, orchestrator, base_config.project_id, pending=base_config
            )
        except TeamComputeQuotaExceededError as exc:
            logger.warning("Scale-up blocked by compute quota for %s: %s", base_name, exc)
            return
    try:
        replica_info = await orchestrator.deploy_replica(base_config, next_index)
    except (OrchestratorError, ProviderConnectionError) as exc:
        logger.warning(
            "Scale-up deploy failed for %s replica %d: %s", base_name, next_index, exc
        )
        return
    live_replicas = await orchestrator.list_replicas(base_name)
    live_replica_names = [
        r.name for r in live_replicas if r.status == ContainerStatus.RUNNING
    ]
    await _upsert_route_with_replicas(
        traffic_router, base_spec, base_name, base_port, live_replica_names
    )
    logger.info(
        "Scaled up %s: added replica %s (total replicas: %d)",
        base_name,
        replica_info.name,
        len(live_replica_names),
    )


async def _scale_down(
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    base_name: str,
    base_port: int,
    base_spec: RouteSpec,
    replica_names_by_index: list[tuple[str, int]],
) -> None:
    """Remove the highest-indexed replica and deregister it from Traefik."""
    if not replica_names_by_index:
        return
    victim_name, _ = replica_names_by_index[-1]
    try:
        victim_info = await orchestrator.get(victim_name)
        await orchestrator.remove(victim_info.id, force=True)
    except (ContainerNotFoundError, ProviderConnectionError, OrchestratorError) as exc:
        logger.warning("Scale-down removal failed for %s: %s", victim_name, exc)
        return
    live_replicas = await orchestrator.list_replicas(base_name)
    live_replica_names = [
        r.name for r in live_replicas if r.status == ContainerStatus.RUNNING
    ]
    await _upsert_route_with_replicas(
        traffic_router, base_spec, base_name, base_port, live_replica_names
    )
    logger.info(
        "Scaled down %s: removed replica %s (remaining replicas: %d)",
        base_name,
        victim_name,
        len(live_replica_names),
    )


async def tick(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
) -> None:
    """Evaluate every enabled scaling policy and apply scale-up or scale-down as needed."""
    policies = await list_enabled_policies(session)
    for runtime in policies:
        try:
            await _evaluate_policy(session, orchestrator, traffic_router, runtime)
        except Exception:
            logger.exception(
                "Unhandled error evaluating scaling policy for %s",
                runtime.policy.container_name,
            )


async def _evaluate_policy(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
    runtime: ScalingPolicyRuntime,
) -> None:
    from app.core.deploy.deployment_history import load_deploy_config_snapshot

    policy = runtime.policy
    base_name = policy.container_name
    base_info = await _base_container_info(orchestrator, base_name)
    if base_info is None:
        logger.warning("Scale-up skipped: base container %s not found", base_name)
        return
    base_config = await load_deploy_config_snapshot(session, base_info.id)
    if base_config is None:
        logger.warning("Scale-up skipped: no stored deploy config for %s", base_name)
        return

    now = datetime.now(UTC)
    in_cooldown = _is_in_cooldown(runtime)

    metric_value = await _measure_metric(
        orchestrator, base_name, policy.metric, traffic_router
    )
    if metric_value is None:
        return

    replica_pairs = await _collect_replica_configs(orchestrator, base_name)
    current_replica_count = len(replica_pairs)
    total_instances = 1 + current_replica_count

    base_spec = await _build_route_spec_for_service(traffic_router, base_name)
    if base_spec is None:
        return

    base_port = base_spec.backend_servers[0].port if base_spec.backend_servers else 80

    in_scale_up_zone = (
        metric_value >= policy.scale_up_threshold
        and total_instances < policy.max_replicas
    )
    in_scale_down_zone = (
        metric_value <= policy.scale_down_threshold
        and total_instances > policy.min_replicas
        and current_replica_count > 0
    )

    scale_up_since = runtime.scale_up_condition_since
    scale_down_since = runtime.scale_down_condition_since

    if in_scale_up_zone:
        if scale_up_since is None:
            scale_up_since = now
        scale_down_since = None
    else:
        scale_up_since = None

    if in_scale_down_zone:
        if scale_down_since is None:
            scale_down_since = now
        if in_scale_up_zone:
            # Prefer scale-up when both zones match (overlapping thresholds).
            scale_down_since = None
    elif not in_scale_up_zone:
        scale_down_since = None

    ready_to_scale_up = (
        in_scale_up_zone
        and not in_cooldown
        and _stabilization_elapsed(
            scale_up_since,
            policy.scale_up_stabilization_seconds,
            now,
        )
    )
    ready_to_scale_down = (
        in_scale_down_zone
        and not in_scale_up_zone
        and not in_cooldown
        and _stabilization_elapsed(
            scale_down_since,
            policy.scale_down_stabilization_seconds,
            now,
        )
    )
    if ready_to_scale_up:
        await _scale_up(
            orchestrator,
            traffic_router,
            base_name,
            base_port,
            base_spec,
            current_replica_count,
            base_config,
            session,
        )
        await record_scale_event(session, base_name)
        return

    if ready_to_scale_down:
        await _scale_down(
            orchestrator, traffic_router, base_name, base_port, base_spec, replica_pairs
        )
        await record_scale_event(session, base_name)
        return

    await update_stabilization_state(
        session,
        base_name,
        scale_up_condition_since=scale_up_since,
        scale_down_condition_since=scale_down_since,
    )


async def run_scaling_loop(
    orchestrator: ContainerOrchestrator,
    traffic_router: TrafficRouter,
) -> None:
    """Background coroutine that runs the scaling engine on a fixed interval.

    Designed to be cancelled cleanly via :func:`asyncio.Task.cancel`.

    Only one control-plane process should run this loop; multiple workers would
    each call :func:`tick` and could issue duplicate scale actions.
    """
    from app.db.engine import get_session_factory

    session_factory = get_session_factory()
    logger.info("Scaling engine started (interval=%ds)", _LOOP_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(_LOOP_INTERVAL_SECONDS)
        try:
            async with session_factory() as session:
                await tick(session, orchestrator, traffic_router)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scaling loop iteration failed")
