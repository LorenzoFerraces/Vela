"""HTTP edge routing (ingress intent) API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_traffic_router, require_admin
from app.core.audit.service import emit_audit_log
from app.core.traffic.traffic_models import RouteInfo, RouteSpec
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import User

router = APIRouter(dependencies=[Depends(get_current_user)])


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
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> RouteInfo:
    """Create or replace a route (admin only)."""
    result = await traffic_router.upsert_route(spec)
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="route.upsert",
        target_type="route",
        target_id=spec.route_id,
        details={"host": spec.host, "path_prefix": spec.path_prefix},
    )
    await session.commit()
    return result


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
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> Response:
    """Remove a route (admin only)."""
    await traffic_router.remove_route(route_id)
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="route.delete",
        target_type="route",
        target_id=route_id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
