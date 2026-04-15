"""HTTP edge routing (ingress intent) API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_traffic_router
from app.core.traffic_models import RouteInfo, RouteSpec
from app.core.traffic_router import TrafficRouter

router = APIRouter()


@router.get("/routes", response_model=list[RouteInfo])
async def list_routes(
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
) -> list[RouteInfo]:
    """List all configured HTTP routes."""
    routes = await traffic_router.list_routes()
    return sorted(routes, key=lambda route: route.route_id)


@router.post("/routes", response_model=RouteInfo)
async def upsert_route(
    spec: RouteSpec,
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
) -> RouteInfo:
    """Create or replace a route."""
    return await traffic_router.upsert_route(spec)


@router.get("/routes/{route_id}", response_model=RouteInfo)
async def get_route(
    route_id: str,
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
) -> RouteInfo:
    """Return a single route by id."""
    return await traffic_router.get_route(route_id)


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: str,
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
) -> Response:
    """Remove a route."""
    await traffic_router.remove_route(route_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
