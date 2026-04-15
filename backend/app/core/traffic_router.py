"""Provider-agnostic edge HTTP routing (ingress) interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.exceptions import RouteNotFoundError
from app.core.traffic_models import RouteInfo, RouteSpec


class TrafficRouter(ABC):
    """Abstract edge proxy integration (Traefik file provider, Kubernetes Ingress, etc.)."""

    @abstractmethod
    async def upsert_route(self, spec: RouteSpec) -> RouteInfo:
        """Create or replace a route."""

    @abstractmethod
    async def remove_route(self, route_id: str) -> None:
        """Remove a route by id."""

    @abstractmethod
    async def get_route(self, route_id: str) -> RouteInfo:
        """Return one route or raise RouteNotFoundError."""

    @abstractmethod
    async def list_routes(self) -> list[RouteInfo]:
        """Return all configured routes."""


class NoopTrafficRouter(TrafficRouter):
    """In-memory router for tests and when edge routing is disabled."""

    def __init__(self) -> None:
        self._routes: dict[str, RouteSpec] = {}

    async def upsert_route(self, spec: RouteSpec) -> RouteInfo:
        self._routes[spec.route_id] = spec.model_copy(deep=True)
        return RouteInfo.from_spec(spec)

    async def remove_route(self, route_id: str) -> None:
        if route_id not in self._routes:
            raise RouteNotFoundError(route_id)
        del self._routes[route_id]

    async def get_route(self, route_id: str) -> RouteInfo:
        spec = self._routes.get(route_id)
        if spec is None:
            raise RouteNotFoundError(route_id)
        return RouteInfo.from_spec(spec)

    async def list_routes(self) -> list[RouteInfo]:
        return [RouteInfo.from_spec(spec) for spec in self._routes.values()]
