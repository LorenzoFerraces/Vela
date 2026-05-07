"""FastAPI dependencies."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.service import get_user_by_id
from app.core.auth.tokens import decode_access_token
from app.core.default_image_builder import DefaultImageBuilder
from app.core.docker_orchestrator import DockerOrchestrator
from app.core.exceptions import NotAuthenticatedError, TrafficRouterError
from app.core.kubernetes_traffic_router import KubernetesTrafficRouter
from app.core.traffic_router import NoopTrafficRouter, TrafficRouter
from app.core.traefik_file_traffic_router import TraefikFileTrafficRouter
from app.db.engine import get_session_factory
from app.db.models import User


@lru_cache(maxsize=1)
def get_orchestrator() -> DockerOrchestrator:
    """Shared Docker-backed orchestrator (one client per process)."""
    return DockerOrchestrator()


@lru_cache(maxsize=1)
def get_image_builder() -> DefaultImageBuilder:
    """Git/local clone + Dockerfile bootstrap + ``docker build``."""
    return DefaultImageBuilder(orchestrator=get_orchestrator())


def _traffic_router_from_env() -> TrafficRouter:
    mode = os.environ.get("VELA_TRAFFIC_ROUTER", "noop").strip().lower()
    match mode:
        case "noop":
            return NoopTrafficRouter()
        case "traefik_file":
            path_str = os.environ.get("VELA_TRAEFIK_DYNAMIC_FILE", "").strip()
            if not path_str:
                raise TrafficRouterError(
                    "VELA_TRAFFIC_ROUTER=traefik_file requires VELA_TRAEFIK_DYNAMIC_FILE "
                    "(absolute path to the dynamic JSON file Traefik loads)."
                )
            reload_container = os.environ.get("VELA_TRAEFIK_RELOAD_CONTAINER", "").strip()
            return TraefikFileTrafficRouter(
                traefik_dynamic_file=Path(path_str),
                reload_container=reload_container or None,
            )
        case "kubernetes":
            return KubernetesTrafficRouter()
        case _:
            raise TrafficRouterError(
                f"Unknown VELA_TRAFFIC_ROUTER={mode!r}; "
                "use noop, traefik_file, or kubernetes."
            )


@lru_cache(maxsize=1)
def get_traffic_router() -> TrafficRouter:
    """Shared edge routing adapter (noop, Traefik file, or Kubernetes scaffold)."""
    return _traffic_router_from_env()


# ---------------------------------------------------------------------------
# Database / auth dependencies
# ---------------------------------------------------------------------------


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy async session for the duration of the request."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)


async def get_current_user(
    token: Annotated[str | None, Depends(_oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve the bearer token to a :class:`User`; raise on any failure."""
    if not token:
        raise NotAuthenticatedError()
    claims = decode_access_token(token)
    user = await get_user_by_id(session, claims.user_id)
    if user is None:
        raise NotAuthenticatedError("User no longer exists.")
    return user
