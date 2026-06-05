"""Kubernetes Ingress / Gateway integration (scaffold for a future implementation)."""

from __future__ import annotations

from app.core.exceptions import TrafficRouterError
from app.core.traffic_models import RouteInfo, RouteSpec
from app.core.traffic_router import TrafficRouter


class KubernetesTrafficRouter(TrafficRouter):
    """Placeholder adapter; wire ``kubernetes`` client and Ingress/Gateway API later."""

    async def upsert_route(self, spec: RouteSpec) -> RouteInfo:
        raise TrafficRouterError(
            "Kubernetes traffic router is not implemented yet. "
            "Use VELA_TRAFFIC_ROUTER=noop or traefik_file for now."
        )

    async def remove_route(self, route_id: str) -> None:
        raise TrafficRouterError(
            f"Kubernetes traffic router is not implemented yet (route_id={route_id!r}). "
            "Use VELA_TRAFFIC_ROUTER=noop or traefik_file for now."
        )

    async def get_route(self, route_id: str) -> RouteInfo:
        raise TrafficRouterError(
            f"Kubernetes traffic router is not implemented yet (route_id={route_id!r}). "
            "Use VELA_TRAFFIC_ROUTER=noop or traefik_file for now."
        )

    async def list_routes(self) -> list[RouteInfo]:
        raise TrafficRouterError(
            "Kubernetes traffic router is not implemented yet. "
            "Use VELA_TRAFFIC_ROUTER=noop or traefik_file for now."
        )
