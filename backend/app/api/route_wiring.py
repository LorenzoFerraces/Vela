"""Register or remove Traefik file-provider routes after container lifecycle events."""

from __future__ import annotations

import logging

from app.core.exceptions import RouteNotFoundError
from app.core.models import ContainerInfo, DeployConfig
from app.core.traffic_models import RouteSpec
from app.core.traffic_router import TrafficRouter

logger = logging.getLogger(__name__)


def backend_port_for_route(config: DeployConfig) -> int:
    """Pick the container port Traefik should forward to."""
    if config.ports:
        return config.ports[0].container_port
    return config.container_listen_port


async def register_route_for_deployed_container(
    *,
    traffic_router: TrafficRouter,
    container_info: ContainerInfo,
    route_host: str,
    path_prefix: str,
    backend_port: int,
    tls_enabled: bool,
) -> None:
    """Publish a ``RouteSpec`` using the container name as ``route_id`` and backend DNS name."""
    trimmed_host = route_host.strip()
    if not trimmed_host:
        return
    # TLS routes get two Traefik routers (``web`` + ``websecure``) so HTTP and HTTPS both match.
    entrypoints = ["web", "websecure"] if tls_enabled else ["web"]
    spec = RouteSpec(
        route_id=container_info.name,
        host=trimmed_host,
        path_prefix=path_prefix,
        backend_host=container_info.name,
        backend_port=backend_port,
        tls_enabled=tls_enabled,
        entrypoints=entrypoints,
    )
    await traffic_router.upsert_route(spec)


async def remove_route_for_container_name(
    *,
    traffic_router: TrafficRouter,
    container_name: str,
) -> None:
    """Best-effort route removal (same ``route_id`` convention as registration)."""
    try:
        await traffic_router.remove_route(container_name)
    except RouteNotFoundError:
        logger.debug("No traffic route for container name %s", container_name)
