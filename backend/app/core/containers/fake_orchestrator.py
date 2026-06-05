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
    deploy_source_fields_from_labels,
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
        """
        Initialize internal in-memory state used by the fake container orchestrator.
        
        Sets up empty container storage, a seeded set of available images, a list for recorded built image tags, and instrumentation fields for the last deploy configuration, verification call history, and per-image verification handlers.
        
        Attributes:
            _containers (dict[str, ContainerInfo]): Mapping of container id to stored container info.
            _images (set[str]): Available image references; initially contains common test images.
            _built_tags (list[str]): Sequence of tags recorded when build_image is called.
            last_deploy_config (DeployConfig | None): The most recent deploy config passed to deploy, or None.
            verify_calls (list[str]): Ordered list of image refs passed to verify_image_reference_available.
            _verify_handlers (dict[str, Callable[[], None]]): Optional per-image handlers invoked during verification.
        """
        self._containers: dict[str, ContainerInfo] = {}
        self._images: set[str] = {"nginx:alpine", "python:3.12-slim"}
        self._built_tags: list[str] = []
        self.last_deploy_config: DeployConfig | None = None
        self.verify_calls: list[str] = []
        self._verify_handlers: dict[str, Callable[[], None]] = {}

    def register_image(self, image_ref: str) -> None:
        """
        Register an image reference as available in the fake orchestrator.
        
        Parameters:
            image_ref (str): Image reference to register; leading and trailing whitespace will be removed before storing.
        """
        self._images.add(image_ref.strip())

    def seed_container(self, info: ContainerInfo) -> None:
        """
        Insert a ContainerInfo into the orchestrator's in-memory container store.
        
        If an entry with the same container id already exists, it is replaced.
        
        Parameters:
            info (ContainerInfo): The container record to store; its `id` field is used as the key.
        """
        self._containers[info.id] = info

    def set_verify_error(self, image_ref: str, error: Exception) -> None:
        """
        Register a verification handler that causes future verification of the given image reference to raise the provided exception.
        
        Parameters:
            image_ref (str): Image reference string to associate with the error (whitespace is stripped).
            error (Exception): Exception instance that will be raised when the image reference is verified.
        """
        def raise_error() -> None:
            raise error

        self._verify_handlers[image_ref.strip()] = raise_error

    async def deploy(self, config: DeployConfig) -> ContainerInfo:
        """
        Create and register a new fake container based on the provided deployment configuration.
        
        Parameters:
            config (DeployConfig): Deployment configuration used to create the container (name, image, labels, routing settings, etc.). The orchestrator's `last_deploy_config` is set to this value.
        
        Returns:
            ContainerInfo: A newly created container record in `RUNNING` state with a generated `id`, the resolved `name`, merged `labels` (including route-related labels when `config.route_host` is set), computed `access_url`, and the current UTC creation timestamp. The container is stored in the orchestrator's internal container registry.
        """
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
        source_kind, source_label = deploy_source_fields_from_labels(labels)
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
            source_kind=source_kind,
            source_label=source_label,
        )
        self._containers[container_id] = info
        return info

    async def start(self, container_id: str) -> ContainerInfo:
        """
        Ensure the specified container is in the RUNNING state and return its ContainerInfo.
        
        Parameters:
            container_id (str): Identifier of the container to start.
        
        Returns:
            ContainerInfo: The container information with `status` set to `ContainerStatus.RUNNING`. If the container was already running, the existing `ContainerInfo` is returned.
        
        Raises:
            ContainerNotFoundError: If no container exists with the given `container_id`.
            ContainerNotRunningError: If the container exists but is in an invalid state for operations.
        """
        info = self._require_container(container_id)
        if info.status == ContainerStatus.RUNNING:
            return info
        updated = info.model_copy(update={"status": ContainerStatus.RUNNING})
        self._containers[container_id] = updated
        return updated

    async def stop(self, container_id: str, *, timeout: int = 10) -> ContainerInfo:
        """
        Stop the stored container and mark its status as stopped.
        
        Parameters:
            container_id (str): Identifier of the container to stop.
            timeout (int): Accepted for API compatibility; ignored by this implementation.
        
        Returns:
            ContainerInfo: The container info updated with `status` set to `ContainerStatus.STOPPED`.
        """
        _ = timeout
        info = self._require_container(container_id)
        updated = info.model_copy(update={"status": ContainerStatus.STOPPED})
        self._containers[container_id] = updated
        return updated

    async def restart(self, container_id: str, *, timeout: int = 10) -> ContainerInfo:
        """
        Restart a container by stopping it and then starting it.
        
        Parameters:
            container_id (str): ID of the container to restart.
            timeout (int): Shutdown timeout in seconds; accepted for API compatibility but ignored by this implementation.
        
        Returns:
            ContainerInfo: The container's updated information after it has been started.
        """
        await self.stop(container_id, timeout=timeout)
        return await self.start(container_id)

    async def remove(self, container_id: str, *, force: bool = False) -> None:
        """
        Remove the container record with the given ID from the orchestrator's in-memory store.
        
        Parameters:
            container_id (str): Identifier of the container to remove.
            force (bool): Ignored in this implementation; accepted for API compatibility.
        
        Raises:
            ContainerNotFoundError: If no container with `container_id` exists.
            ContainerNotRunningError: If the container exists but is in an invalid state for operations.
        """
        _ = force
        self._require_container(container_id)
        del self._containers[container_id]

    async def get(self, container_id: str) -> ContainerInfo:
        """
        Retrieve stored container information for the given container id.
        
        Returns:
            ContainerInfo: The container record corresponding to the provided id.
        
        Raises:
            ContainerNotFoundError: If no container with the given id exists.
            ContainerNotRunningError: If the container exists but is in an invalid state for operations.
        """
        return self._require_container(container_id)

    async def list(
        self,
        *,
        status: ContainerStatus | None = None,
        owner_id: str | None = None,
    ) -> list[ContainerInfo]:
        """
        List stored containers, optionally filtered by status and owner.
        
        Parameters:
            status (ContainerStatus | None): If provided, include only containers whose `status` equals this value.
            owner_id (str | None): If provided, include only containers whose labels contain `VELA_OWNER_LABEL` equal to this value.
        
        Returns:
            list[ContainerInfo]: A list of ContainerInfo objects matching the provided filters.
        """
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
        """
        Retrieve the logs for the specified container.
        
        Parameters:
        	container_id (str): ID of the container whose logs are requested.
        	tail (int): Number of most-recent lines to include; ignored by this fake orchestrator.
        
        Returns:
        	logs (str): The container logs as a string (for the fake orchestrator this is the fixed value "log line\n").
        """
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
        """
        Yield a single chunk of fake raw log data for the specified container.
        
        Ensures the container exists, then yields one bytes chunk containing "log line\n".
        Parameters:
            container_id (str): Identifier of the container whose logs are requested.
            tail (int | None): Ignored; kept for API compatibility.
            follow (bool): Ignored; kept for API compatibility.
        
        Returns:
            AsyncIterator[bytes]: An async iterator that yields one bytes chunk (b"log line\n").
        """
        _ = tail, follow
        self._require_container(container_id)
        yield b"log line\n"

    async def get_stats(self, container_id: str) -> ContainerStats:
        """
        Return a snapshot of resource usage statistics for the specified container.
        
        Parameters:
            container_id (str): Identifier of the container to query.
        
        Returns:
            ContainerStats: Snapshot containing the container id, timestamp, CPU percent, memory usage and limit, and memory percent.
        
        Raises:
            ContainerNotFoundError: If no container exists with the given id.
            ContainerNotRunningError: If the container exists but is not in a valid lifecycle state for inspection.
        """
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
        """
        Provide the simulated health status for a container.
        
        Returns:
            HealthResult: A result with `status` set to `HealthStatus.HEALTHY` and `timestamp` set to the current UTC time.
        
        Raises:
            ContainerNotFoundError: If no container exists with the given `container_id`.
            ContainerNotRunningError: If the container exists but is in an invalid state for health checks.
        """
        self._require_container(container_id)
        return HealthResult(
            status=HealthStatus.HEALTHY,
            timestamp=datetime.now(timezone.utc),
        )

    async def pull_image(self, image: str, *, tag: str = "latest") -> None:
        """
        Marks an image reference as available in the fake orchestrator's in-memory image store.
        
        If `image` contains no `:`, the function appends `:{tag}` to form the resolved image reference; if `image` already contains a `:`, it is used as given and marked available.
        
        Parameters:
            image (str): Image name or reference (e.g., "nginx" or "registry.example.com/nginx:1.2").
            tag (str): Tag to append when `image` has no explicit tag (default: "latest").
        """
        self.register_image(f"{image}:{tag}" if ":" not in image else image)

    async def build_image(
        self, path: str, *, tag: str, dockerfile: str = "Dockerfile"
    ) -> str:
        """
        Create a fake image record and return a synthetic image digest.
        
        Parameters:
            path (str): Ignored; included for API compatibility.
            tag (str): The image tag to register and record as built.
            dockerfile (str): Ignored; included for API compatibility.
        
        Returns:
            digest (str): A synthetic digest string in the form `sha256:fake-<tag>` where `:` in the tag is replaced by `-`.
        """
        _ = path, dockerfile
        self.register_image(tag)
        self._built_tags.append(tag)
        return f"sha256:fake-{tag.replace(':', '-')}"

    async def list_images(self) -> list[str]:
        """
        Get a sorted list of available image references.
        
        Returns:
            list[str]: Image reference strings sorted in ascending order.
        """
        return sorted(self._images)

    async def verify_image_reference_available(self, image_ref: str) -> None:
        """
        Validate that a given image reference is available to the fake orchestrator.
        
        This records the stripped image reference in `verify_calls` and, if a per-image handler was registered, runs that handler. If the reference is already known to the fake orchestrator or begins with "vela/", the check succeeds. References starting with "missing:" cause an ImageNotFoundError; those starting with "denied:" cause a RegistryAccessDeniedError. If the reference contains ":" or "/", it is registered as available and the check succeeds. All other references raise ImageNotFoundError.
        
        Parameters:
            image_ref (str): The image reference to verify; leading and trailing whitespace are ignored.
        
        Raises:
            ImageNotFoundError: If the image is determined to be missing.
            RegistryAccessDeniedError: If access to the registry for the image is denied.
        """
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
        """
        Retrieve a stored container by its ID and ensure its status is one of the valid runtime states.
        
        Parameters:
            container_id (str): Identifier of the container to retrieve.
        
        Returns:
            ContainerInfo: The container information for the given `container_id`.
        
        Raises:
            ContainerNotFoundError: If no container exists with the given `container_id`.
            ContainerNotRunningError: If the container exists but its status is not one of
                RUNNING, STOPPED, CREATED, PAUSED, or RESTARTING.
        """
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
    """
    Get the shared FakeContainerOrchestrator singleton used for end-to-end and development tests.
    
    The instance is lazily created on first call and pre-registers the image "nginx:alpine".
    
    Returns:
        FakeContainerOrchestrator: the singleton orchestrator instance.
    """
    global _shared_fake
    if _shared_fake is None:
        _shared_fake = FakeContainerOrchestrator()
        _shared_fake.register_image("nginx:alpine")
    return _shared_fake
