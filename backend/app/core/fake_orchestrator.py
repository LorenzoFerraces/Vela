"""In-memory container orchestrator for tests and E2E (no Docker daemon)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Callable

from app.core.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_MANAGED_VALUE,
    VELA_OWNER_LABEL,
    VELA_ROUTE_HOST_LABEL,
    VELA_ROUTE_PATH_PREFIX_LABEL,
    VELA_ROUTE_TLS_LABEL,
    _access_url_from_route_labels,
)
from app.core.enums import ContainerStatus, HealthStatus
from app.core.exceptions import (
    ContainerNotFoundError,
    ContainerNotRunningError,
    ImageNotFoundError,
    RegistryAccessDeniedError,
)
from app.core.models import ContainerInfo, ContainerStats, DeployConfig, HealthResult
from app.core.orchestrator import ContainerOrchestrator


class FakeContainerOrchestrator(ContainerOrchestrator):
    """Process-local fake that tracks containers and images without Docker."""

    def __init__(self) -> None:
        self._containers: dict[str, ContainerInfo] = {}
        self._images: set[str] = {"nginx:alpine", "python:3.12-slim"}
        self._built_tags: list[str] = []
        self.last_deploy_config: DeployConfig | None = None
        self.verify_calls: list[str] = []
        self._verify_handlers: dict[str, Callable[[], None]] = {}

    def register_image(self, image_ref: str) -> None:
        self._images.add(image_ref.strip())

    def seed_container(self, info: ContainerInfo) -> None:
        self._containers[info.id] = info

    def set_verify_error(self, image_ref: str, error: Exception) -> None:
        def raise_error() -> None:
            raise error

        self._verify_handlers[image_ref.strip()] = raise_error

    async def deploy(self, config: DeployConfig) -> ContainerInfo:
        self.last_deploy_config = config
        labels = {
            VELA_MANAGED_LABEL: VELA_MANAGED_VALUE,
            **config.labels,
        }
        route_host = (config.route_host or "").strip()
        if route_host:
            labels[VELA_ROUTE_HOST_LABEL] = route_host.lower()
            labels[VELA_ROUTE_PATH_PREFIX_LABEL] = config.route_path_prefix
            labels[VELA_ROUTE_TLS_LABEL] = "true" if config.route_tls else "false"

        container_id = f"fake-{uuid.uuid4().hex[:12]}"
        name = config.name or f"vela-{container_id[-8:]}"
        info = ContainerInfo(
            id=container_id,
            name=name,
            image=config.image,
            status=ContainerStatus.RUNNING,
            created_at=datetime.now(timezone.utc),
            ports=[],
            labels=labels,
            health=HealthStatus.NONE,
            access_url=_access_url_from_route_labels(labels),
        )
        self._containers[container_id] = info
        return info

    async def start(self, container_id: str) -> ContainerInfo:
        info = self._require_container(container_id)
        if info.status == ContainerStatus.RUNNING:
            return info
        updated = info.model_copy(update={"status": ContainerStatus.RUNNING})
        self._containers[container_id] = updated
        return updated

    async def stop(self, container_id: str, *, timeout: int = 10) -> ContainerInfo:
        _ = timeout
        info = self._require_container(container_id)
        updated = info.model_copy(update={"status": ContainerStatus.STOPPED})
        self._containers[container_id] = updated
        return updated

    async def restart(self, container_id: str, *, timeout: int = 10) -> ContainerInfo:
        await self.stop(container_id, timeout=timeout)
        return await self.start(container_id)

    async def remove(self, container_id: str, *, force: bool = False) -> None:
        _ = force
        self._require_container(container_id)
        del self._containers[container_id]

    async def get(self, container_id: str) -> ContainerInfo:
        return self._require_container(container_id)

    async def list(
        self,
        *,
        status: ContainerStatus | None = None,
        owner_id: str | None = None,
    ) -> list[ContainerInfo]:
        rows = list(self._containers.values())
        if owner_id is not None:
            rows = [
                row
                for row in rows
                if row.labels.get(VELA_OWNER_LABEL) == owner_id
            ]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return rows

    async def logs(self, container_id: str, *, tail: int = 100) -> str:
        _ = tail
        self._require_container(container_id)
        return "log line\n"

    async def stream_logs(
        self,
        container_id: str,
        *,
        tail: int | None = 100,
        follow: bool = True,
    ) -> AsyncIterator[bytes]:
        _ = tail, follow
        self._require_container(container_id)
        yield b"log line\n"

    async def get_stats(self, container_id: str) -> ContainerStats:
        self._require_container(container_id)
        return ContainerStats(
            container_id=container_id,
            timestamp=datetime.now(timezone.utc),
            cpu_percent=1.0,
            memory_usage_bytes=1000,
            memory_limit_bytes=2000,
            memory_percent=50.0,
        )

    async def get_health(self, container_id: str) -> HealthResult:
        self._require_container(container_id)
        return HealthResult(
            status=HealthStatus.HEALTHY,
            timestamp=datetime.now(timezone.utc),
        )

    async def pull_image(self, image: str, *, tag: str = "latest") -> None:
        self.register_image(f"{image}:{tag}" if ":" not in image else image)

    async def build_image(
        self, path: str, *, tag: str, dockerfile: str = "Dockerfile"
    ) -> str:
        _ = path, dockerfile
        self.register_image(tag)
        self._built_tags.append(tag)
        return f"sha256:fake-{tag.replace(':', '-')}"

    async def list_images(self) -> list[str]:
        return sorted(self._images)

    async def verify_image_reference_available(self, image_ref: str) -> None:
        stripped = image_ref.strip()
        self.verify_calls.append(stripped)
        handler = self._verify_handlers.get(stripped)
        if handler is not None:
            handler()
            return
        if stripped in self._images or stripped.startswith("vela/"):
            return
        if stripped.startswith("missing:"):
            raise ImageNotFoundError(stripped)
        if stripped.startswith("denied:"):
            raise RegistryAccessDeniedError(stripped)
        if ":" in stripped or "/" in stripped:
            self.register_image(stripped)
            return
        raise ImageNotFoundError(stripped)

    def _require_container(self, container_id: str) -> ContainerInfo:
        info = self._containers.get(container_id)
        if info is None:
            raise ContainerNotFoundError(container_id)
        if info.status not in (
            ContainerStatus.RUNNING,
            ContainerStatus.STOPPED,
            ContainerStatus.CREATED,
            ContainerStatus.PAUSED,
            ContainerStatus.RESTARTING,
        ):
            raise ContainerNotRunningError(container_id)
        return info


_shared_fake: FakeContainerOrchestrator | None = None


def get_shared_fake_orchestrator() -> FakeContainerOrchestrator:
    """Singleton fake orchestrator for E2E / dev test mode."""
    global _shared_fake
    if _shared_fake is None:
        _shared_fake = FakeContainerOrchestrator()
        _shared_fake.register_image("nginx:alpine")
    return _shared_fake
