"""FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from app.core.docker_orchestrator import DockerOrchestrator


@lru_cache(maxsize=1)
def get_orchestrator() -> DockerOrchestrator:
    """Shared Docker-backed orchestrator (one client per process)."""
    return DockerOrchestrator()
