"""Deploy-time Docker network alias wiring."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import docker.errors

from app.core.containers.docker_orchestrator import DockerOrchestrator
from app.core.models import DeployConfig


class _StubContainer:
    """Container stub recording whether it was started."""
    def __init__(self, container_id: str) -> None:
        """Store the stub container id and initial state."""
        self.id = container_id
        self.started = False

    def start(self) -> None:
        """Mark the container as started."""
        self.started = True


class _StubNetwork:
    """Network stub collecting connect calls."""
    def __init__(self) -> None:
        """Start with an empty connect log."""
        self.connect_calls: list[tuple[Any, dict[str, Any]]] = []

    def connect(self, container: Any, **kwargs: Any) -> None:
        """Record the connected container and kwargs."""
        self.connect_calls.append((container, kwargs))


class _StubContainers:
    """Container registry stub handing out stub containers."""
    def __init__(self) -> None:
        """Start with an empty created log."""
        self.created: list[tuple[str, dict[str, Any]]] = []
        self._last: _StubContainer | None = None

    def get(self, name: str) -> _StubContainer:
        """Always raise NotFound so deploy creates a fresh container."""
        raise docker.errors.NotFound(f"container {name} not found")

    def create(self, image: str, **kwargs: Any) -> _StubContainer:
        """Record the create call and return a new stub container."""
        self.created.append((image, kwargs))
        self._last = _StubContainer("stub-container-id")
        return self._last


class _StubNetworks:
    """Network registry stub for the stack network."""
    def __init__(self, network: _StubNetwork) -> None:
        """Store the network to hand out."""
        self._network = network

    def list(self, filters: dict[str, Any] | None = None) -> list[SimpleNamespace]:
        """Report the default network as present."""
        return [SimpleNamespace(name="vela-workloads")]

    def get(self, name: str) -> _StubNetwork:
        """Return the shared stub network for the stack network name."""
        assert name == "vela-stack-testnet"
        return self._network


class _StubImages:
    """Image registry stub that treats every reference as present."""
    def get(self, image_ref: str) -> object:
        """Return a placeholder image object."""
        return object()


class _StubClient:
    """Docker client stub wiring the container and network stubs together."""
    def __init__(self) -> None:
        """Build the sub-clients sharing one stack network stub."""
        self.network = _StubNetwork()
        self.containers = _StubContainers()
        self.networks = _StubNetworks(self.network)
        self.images = _StubImages()


def _orchestrator(client: _StubClient) -> DockerOrchestrator:
    """Build a DockerOrchestrator around the stub client."""
    orch = DockerOrchestrator.__new__(DockerOrchestrator)
    orch._client = client
    orch._default_network = "vela-workloads"
    orch._default_network_ensured = False
    orch._default_network_lock = threading.Lock()
    return orch


def test_deploy_connects_stack_network_with_aliases_after_start() -> None:
    """Deploy connects the stack network with aliases after starting."""
    client = _StubClient()
    orch = _orchestrator(client)
    config = DeployConfig(
        image="postgres:16",
        name="Commit-y-me-voy_postgres",
        env_vars={},
        network="vela-stack-testnet",
        network_aliases=["postgres"],
    )

    orch._inspect_container_with_size = lambda container_id: {  # type: ignore[method-assign]
        "Id": "stub-container-id",
        "Name": "/Commit-y-me-voy_postgres",
        "Config": {"Image": "postgres:16", "Labels": {}},
        "State": {"Status": "running", "Health": None},
        "Created": "2026-01-01T00:00:00.000000000Z",
        "NetworkSettings": {"Ports": {}},
    }

    import asyncio

    asyncio.run(orch.deploy(config))

    assert "network" not in client.containers.created[0][1]
    assert client.network.connect_calls == [
        (client.containers._last, {"aliases": ["postgres"]}),
    ]
