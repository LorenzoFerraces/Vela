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
from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.containers.docker_orchestrator import DockerOrchestrator
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import (
    NotAuthenticatedError,
    ObjectStorageError,
    TrafficRouterError,
)
from app.core.traffic.kubernetes_traffic_router import KubernetesTrafficRouter
from app.core.storage.memory import InMemoryObjectStorage
from app.core.storage.object_storage import ObjectStorage
from app.core.storage.r2 import CloudflareR2ObjectStorage
from app.core.traffic.traffic_router import NoopTrafficRouter, TrafficRouter
from app.core.traffic.traefik_file_traffic_router import TraefikFileTrafficRouter
from app.db.engine import get_session_factory
from app.db.models import User


@lru_cache(maxsize=1)
def get_orchestrator() -> ContainerOrchestrator:
    """
    Provide the shared container orchestrator instance for the application.

    Returns:
        ContainerOrchestrator: Shared orchestrator instance. If the environment variable
        VELA_FAKE_ORCHESTRATOR is set to "1" (after trimming), returns the shared in-memory
        fake orchestrator; otherwise returns a DockerOrchestrator instance.
    """
    if os.environ.get("VELA_FAKE_ORCHESTRATOR", "").strip() == "1":
        from app.core.containers.fake_orchestrator import get_shared_fake_orchestrator

        return get_shared_fake_orchestrator()
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
            reload_container = os.environ.get(
                "VELA_TRAEFIK_RELOAD_CONTAINER", ""
            ).strip()
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


def _object_storage_from_env() -> ObjectStorage:
    mode = os.environ.get("VELA_OBJECT_STORAGE", "memory").strip().lower()
    match mode:
        case "memory":
            public_base_url = os.environ.get(
                "VELA_OBJECT_STORAGE_PUBLIC_BASE_URL", "https://storage.test"
            ).strip()
            return InMemoryObjectStorage(public_base_url=public_base_url)
        case "r2":
            account_id = os.environ.get("VELA_R2_ACCOUNT_ID", "").strip()
            access_key_id = os.environ.get("VELA_R2_ACCESS_KEY_ID", "").strip()
            secret_access_key = os.environ.get("VELA_R2_SECRET_ACCESS_KEY", "").strip()
            bucket = os.environ.get("VELA_R2_BUCKET", "").strip()
            public_base_url = os.environ.get("VELA_R2_PUBLIC_BASE_URL", "").strip()
            missing = [
                name
                for name, value in (
                    ("VELA_R2_ACCOUNT_ID", account_id),
                    ("VELA_R2_ACCESS_KEY_ID", access_key_id),
                    ("VELA_R2_SECRET_ACCESS_KEY", secret_access_key),
                    ("VELA_R2_BUCKET", bucket),
                    ("VELA_R2_PUBLIC_BASE_URL", public_base_url),
                )
                if not value
            ]
            if missing:
                raise ObjectStorageError(
                    f"VELA_OBJECT_STORAGE=r2 requires: {', '.join(missing)}."
                )
            return CloudflareR2ObjectStorage(
                account_id=account_id,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                bucket=bucket,
                public_base_url=public_base_url,
            )
        case _:
            raise ObjectStorageError(
                f"Unknown VELA_OBJECT_STORAGE={mode!r}; use memory or r2."
            )


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """Shared blob storage adapter (in-memory or Cloudflare R2)."""
    return _object_storage_from_env()


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
