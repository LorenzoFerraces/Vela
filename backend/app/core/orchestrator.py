from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.core.enums import ContainerStatus
from app.core.models import ContainerInfo, ContainerStats, DeployConfig, HealthResult


class ContainerOrchestrator(ABC):
    """Provider-agnostic interface for container lifecycle management.

    Concrete implementations (Docker, Kubernetes, etc.) must implement every
    abstract method. All methods are async to accommodate both local daemons
    and remote API calls.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def deploy(self, config: DeployConfig) -> ContainerInfo:
        """Create and start a container from the given configuration."""

    @abstractmethod
    async def start(self, container_id: str) -> ContainerInfo:
        """Start a stopped container."""

    @abstractmethod
    async def stop(self, container_id: str, *, timeout: int = 10) -> ContainerInfo:
        """Gracefully stop a running container.

        Args:
            timeout: Seconds to wait before forcefully killing the container.
        """

    @abstractmethod
    async def restart(self, container_id: str, *, timeout: int = 10) -> ContainerInfo:
        """Restart a container (stop then start)."""

    @abstractmethod
    async def remove(self, container_id: str, *, force: bool = False) -> None:
        """Remove a container.

        Args:
            force: If True, kill the container before removing it.
        """

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @abstractmethod
    async def get(self, container_id: str) -> ContainerInfo:
        """Return detailed information about a single managed container."""

    @abstractmethod
    async def list(
        self,
        *,
        status: ContainerStatus | None = None,
        owner_id: str | None = None,
    ) -> list[ContainerInfo]:
        """List all managed containers, optionally filtered by status and owner."""

    @abstractmethod
    async def logs(self, container_id: str, *, tail: int = 100) -> str:
        """Return the most recent log lines for a container."""

    @abstractmethod
    async def stream_logs(
        self,
        container_id: str,
        *,
        tail: int | None = 100,
        follow: bool = True,
    ) -> AsyncIterator[bytes]:
        """Yield log chunks from the runtime (blocking iterator wrapped for async consumption)."""

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_stats(self, container_id: str) -> ContainerStats:
        """Return a point-in-time resource usage snapshot for a container."""

    @abstractmethod
    async def get_health(self, container_id: str) -> HealthResult:
        """Return the latest health check result for a container."""

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    @abstractmethod
    async def pull_image(self, image: str, *, tag: str = "latest") -> None:
        """Pull an image from a registry."""

    @abstractmethod
    async def build_image(
        self, path: str, *, tag: str, dockerfile: str = "Dockerfile"
    ) -> str:
        """Build an image from a build context directory.

        Returns:
            The image ID of the newly built image.
        """

    @abstractmethod
    async def list_images(self) -> list[str]:
        """List available image tags on the host."""

    @abstractmethod
    async def verify_image_reference_available(self, image_ref: str) -> None:
        """Confirm ``image_ref`` exists locally or on a registry.

        Raises:
            ImageNotFoundError: The reference is not present locally and not found on the registry.
            RegistryAccessDeniedError: The registry returned 401/403 for the manifest lookup.
            ProviderConnectionError: The runtime or registry could not be reached.
        """
