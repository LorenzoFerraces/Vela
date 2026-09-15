"""Deploy-time Docker network alias wiring."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import docker.errors

from app.core.containers.docker_orchestrator import DockerOrchestrator
from app.core.models import DeployConfig


class _StubContainer:
    def __init__(self, container_id: str) -> None:
        self.id = container_id
        self.started = False

    def start(self) -> None:
        self.started = True


class _StubNetwork:
    def __init__(self) -> None:
        self.connect_calls: list[tuple[Any, dict[str, Any]]] = []

    def connect(self, container: Any, **kwargs: Any) -> None:
        self.connect_calls.append((container, kwargs))


class _StubContainers:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, Any]]] = []
        self._last: _StubContainer | None = None

    def get(self, name: str) -> _StubContainer:
        raise docker.errors.NotFound(f"container {name} not found")

    def create(self, image: str, **kwargs: Any) -> _StubContainer:
        self.created.append((image, kwargs))
        self._last = _StubContainer("stub-container-id")
        return self._last


class _StubNetworks:
    def __init__(self, network: _StubNetwork) -> None:
        self._network = network

    def list(self, filters: dict[str, Any] | None = None) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="vela-workloads")]

    def get(self, name: str) -> _StubNetwork:
        assert name == "vela-stack-testnet"
        return self._network


class _StubImages:
    def get(self, image_ref: str) -> object:
        return object()


class _StubClient:
    def __init__(self) -> None:
        self.network = _StubNetwork()
        self.containers = _StubContainers()
        self.networks = _StubNetworks(self.network)
        self.images = _StubImages()


def _orchestrator(client: _StubClient) -> DockerOrchestrator:
    orch = DockerOrchestrator.__new__(DockerOrchestrator)
    orch._client = client
    orch._default_network = "vela-workloads"
    orch._default_network_ensured = False
    orch._default_network_lock = threading.Lock()
    return orch


def test_deploy_connects_stack_network_with_aliases_after_start() -> None:
    client = _StubClient()
    orch = _orchestrator(client)
    config = DeployConfig(
        image="postgres:16",
        name="Commit-y-me-voy_postgres",
        env_vars={},
        network="vela-stack-testnet",
        network_aliases=["postgres"],
    )

    orch._inspect_container_with_size = lambda _container_id: {
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
