"""FastAPI dependencies."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.core.default_image_builder import DefaultImageBuilder
from app.core.docker_orchestrator import DockerOrchestrator
from app.core.exceptions import TrafficRouterError
from app.core.kubernetes_traffic_router import KubernetesTrafficRouter
from app.core.traffic_router import NoopTrafficRouter, TrafficRouter
from app.core.traefik_file_traffic_router import TraefikFileTrafficRouter


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
            return TraefikFileTrafficRouter(traefik_dynamic_file=Path(path_str))
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
