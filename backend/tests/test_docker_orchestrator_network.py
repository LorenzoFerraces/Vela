"""Tests for default-network auto-creation and Traefik stack-network attach."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import docker.errors
import pytest

from app.core.containers.docker_orchestrator import DockerOrchestrator


class _StubNetworks:
    """Fake docker networks collection backed by a name list."""

    def __init__(self, names: list[str]) -> None:
        """Store initial network names and start an empty created log."""
        self._names = list(names)
        self.created: list[str] = []

    def list(self, filters: dict[str, Any] | None = None) -> list[SimpleNamespace]:
        """Return all known networks as name-only objects."""
        return [SimpleNamespace(name=n) for n in self._names]

    def create(self, name: str, driver: str = "bridge") -> None:
        """Record the created name and add it to the list."""
        self.created.append(name)
        self._names.append(name)


class _StubClient:
    """Fake docker client exposing only the networks collection."""

    def __init__(self, names: list[str]) -> None:
        """Wrap the given network names in a stub networks collection."""
        self.networks = _StubNetworks(names)


def _orchestrator(names: list[str]) -> tuple[DockerOrchestrator, _StubNetworks]:
    """Build a DockerOrchestrator bypassing __init__, wired to stub networks."""
    client = _StubClient(names)
    orch = DockerOrchestrator.__new__(DockerOrchestrator)
    orch._client = client
    orch._default_network = "vela-workloads"
    orch._default_network_ensured = False
    orch._default_network_lock = threading.Lock()
    return orch, client.networks


def test_ensure_default_network_creates_missing_network() -> None:
    """A missing default network is created on first ensure."""
    orch, networks = _orchestrator([])
    orch._ensure_default_network_sync()
    assert networks.created == ["vela-workloads"]
    assert orch._default_network_ensured is True


def test_ensure_default_network_skips_existing() -> None:
    """An already-present default network is not created again."""
    orch, networks = _orchestrator(["vela-workloads"])
    orch._ensure_default_network_sync()
    assert networks.created == []


def test_ensure_default_network_runs_once() -> None:
    """Repeated ensure calls create the network only once."""
    orch, networks = _orchestrator([])
    orch._ensure_default_network_sync()
    orch._ensure_default_network_sync()
    assert networks.created == ["vela-workloads"]


class _ProxyStubContainer:
    """Fake container identified only by its name."""

    def __init__(self, name: str) -> None:
        """Store the container name."""
        self.name = name


class _ProxyStubNetwork:
    """Fake network recording connect/disconnect/remove calls."""

    def __init__(
        self,
        name: str,
        *,
        connect_error: Exception | None = None,
    ) -> None:
        """Store the name and an optional error to raise on connect."""
        self.name = name
        self.connect_error = connect_error
        self.connect_calls: list[tuple[Any, dict[str, Any]]] = []
        self.disconnect_calls: list[tuple[Any, dict[str, Any]]] = []
        self.events: list[str] = []
        self.remove_calls = 0

    def connect(self, container: Any, **kwargs: Any) -> None:
        """Record the call; raise the configured error, if any."""
        self.connect_calls.append((container, kwargs))
        if self.connect_error is not None:
            raise self.connect_error

    def disconnect(self, container: Any, **kwargs: Any) -> None:
        """Record a disconnect call and append to the event log."""
        self.events.append("disconnect")
        self.disconnect_calls.append((container, kwargs))

    def remove(self) -> None:
        """Record a remove call and append to the event log."""
        self.events.append("remove")
        self.remove_calls += 1


class _ProxyStubNetworks:
    """Fake networks collection handing out _ProxyStubNetwork objects."""

    def __init__(
        self,
        names: list[str],
        *,
        connect_error: Exception | None = None,
    ) -> None:
        """Build stub networks for the names, sharing one connect error."""
        self._connect_error = connect_error
        self._by_name = {
            name: _ProxyStubNetwork(name, connect_error=connect_error) for name in names
        }
        self.created: list[str] = []

    def list(self, filters: dict[str, Any] | None = None) -> list[_ProxyStubNetwork]:
        """Return stub networks, filtered by name substring when asked."""
        networks = list(self._by_name.values())
        if filters and "name" in filters:
            needle = filters["name"]
            return [network for network in networks if needle in network.name]
        return networks

    def create(self, name: str, driver: str = "bridge") -> _ProxyStubNetwork:
        """Record and return a new stub network with the shared connect error."""
        self.created.append(name)
        network = _ProxyStubNetwork(name, connect_error=self._connect_error)
        self._by_name[name] = network
        return network

    def get(self, name: str) -> _ProxyStubNetwork:
        """Return the stub network by name or raise NotFound."""
        if name not in self._by_name:
            raise docker.errors.NotFound(f"network {name} not found")
        return self._by_name[name]


class _ProxyStubContainers:
    """Fake containers collection that also logs get calls."""

    def __init__(self, containers: dict[str, _ProxyStubContainer]) -> None:
        """Store the name-to-container map."""
        self._containers = containers
        self.get_calls: list[str] = []

    def get(self, name: str) -> _ProxyStubContainer:
        """Record the lookup; raise NotFound for unknown names."""
        self.get_calls.append(name)
        if name not in self._containers:
            raise docker.errors.NotFound(f"container {name} not found")
        return self._containers[name]


class _ProxyStubClient:
    """Fake docker client with stub containers and networks."""

    def __init__(
        self,
        network_names: list[str],
        *,
        proxy_name: str = "vela-traefik",
        proxy_missing: bool = False,
        connect_error: Exception | None = None,
    ) -> None:
        """Wire a proxy container (optionally missing) and stub networks."""
        self.proxy_container = _ProxyStubContainer(proxy_name)
        self.containers = _ProxyStubContainers(
            {} if proxy_missing else {proxy_name: self.proxy_container}
        )
        self.networks = _ProxyStubNetworks(
            network_names, connect_error=connect_error
        )


def _proxy_orchestrator(
    network_names: list[str],
    *,
    proxy_container: str | None = "vela-traefik",
    proxy_missing: bool = False,
    connect_error: Exception | None = None,
) -> tuple[DockerOrchestrator, _ProxyStubClient]:
    """Build a DockerOrchestrator with a proxy-aware stub client."""
    client = _ProxyStubClient(
        network_names,
        proxy_missing=proxy_missing,
        connect_error=connect_error,
    )
    orch = DockerOrchestrator.__new__(DockerOrchestrator)
    orch._client = client
    orch._default_network = "vela-workloads"
    orch._default_network_ensured = False
    orch._default_network_lock = threading.Lock()
    orch._proxy_container = proxy_container
    return orch, client


def _connected_network_names(client: _ProxyStubClient) -> list[str]:
    """Return names of networks that received at least one connect call."""
    return [
        network.name
        for network in client.networks.list()
        if network.connect_calls
    ]


def test_create_network_attaches_proxy_container() -> None:
    """Creating a stack network connects the proxy container to it."""
    orch, client = _proxy_orchestrator([])
    asyncio.run(orch.create_network("vela-stack-abc"))
    assert client.networks.created == ["vela-stack-abc"]
    network = client.networks.get("vela-stack-abc")
    assert network.connect_calls == [(client.proxy_container, {})]


def test_create_network_attaches_proxy_when_network_already_exists() -> None:
    """An existing stack network still gets the proxy attached."""
    orch, client = _proxy_orchestrator(["vela-stack-abc"])
    asyncio.run(orch.create_network("vela-stack-abc"))
    assert client.networks.created == []
    network = client.networks.get("vela-stack-abc")
    assert network.connect_calls == [(client.proxy_container, {})]


def test_create_network_ignores_already_connected_api_error() -> None:
    """A connect error saying the endpoint already exists is ignored."""
    already_connected = docker.errors.APIError(
        "endpoint with name vela-traefik already exists in network vela-stack-abc"
    )
    orch, client = _proxy_orchestrator(
        ["vela-stack-abc"],
        connect_error=already_connected,
    )
    asyncio.run(orch.create_network("vela-stack-abc"))
    network = client.networks.get("vela-stack-abc")
    assert network.connect_calls == [(client.proxy_container, {})]


def test_create_network_succeeds_when_proxy_container_missing() -> None:
    """Network creation succeeds when the proxy container is missing."""
    orch, client = _proxy_orchestrator([], proxy_missing=True)
    asyncio.run(orch.create_network("vela-stack-abc"))
    assert client.networks.created == ["vela-stack-abc"]
    assert client.containers.get_calls == ["vela-traefik"]
    network = client.networks.get("vela-stack-abc")
    assert network.connect_calls == []


def test_create_network_skips_proxy_when_name_empty() -> None:
    """An empty proxy name skips container lookups and connects."""
    orch, client = _proxy_orchestrator([], proxy_container="")
    asyncio.run(orch.create_network("vela-stack-abc"))
    assert client.networks.created == ["vela-stack-abc"]
    assert client.containers.get_calls == []
    network = client.networks.get("vela-stack-abc")
    assert network.connect_calls == []


def test_remove_network_disconnects_proxy_before_remove() -> None:
    """Removal disconnects the proxy before removing the network."""
    orch, client = _proxy_orchestrator(["vela-stack-abc"])
    asyncio.run(orch.remove_network("vela-stack-abc"))
    network = client.networks.get("vela-stack-abc")
    assert network.events == ["disconnect", "remove"]
    assert network.disconnect_calls == [(client.proxy_container, {"force": True})]
    assert network.remove_calls == 1


def test_remove_network_still_removes_when_proxy_missing() -> None:
    """The network is still removed when the proxy container is gone."""
    orch, client = _proxy_orchestrator(["vela-stack-abc"], proxy_missing=True)
    asyncio.run(orch.remove_network("vela-stack-abc"))
    network = client.networks.get("vela-stack-abc")
    assert network.events == ["remove"]
    assert network.remove_calls == 1


def test_create_network_reconciles_existing_vela_stack_networks() -> None:
    """Creation attaches the proxy to every existing vela-stack network."""
    orch, client = _proxy_orchestrator(["vela-stack-old", "vela-workloads"])
    asyncio.run(orch.create_network("vela-stack-abc"))
    assert _connected_network_names(client) == ["vela-stack-old", "vela-stack-abc"]
    assert client.networks.get("vela-workloads").connect_calls == []
    assert client.networks.get("vela-stack-abc").connect_calls == [
        (client.proxy_container, {})
    ]
    assert client.networks.get("vela-stack-old").connect_calls == [
        (client.proxy_container, {})
    ]


def test_constructor_reads_proxy_container_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The constructor reads the proxy container name from the environment."""
    monkeypatch.setenv("VELA_TRAEFIK_RELOAD_CONTAINER", "vela-traefik")
    client = _ProxyStubClient([])
    orch = DockerOrchestrator(client=client)
    assert orch._proxy_container == "vela-traefik"


def test_constructor_empty_proxy_container_disables_attach() -> None:
    """An empty proxy_container is stored as None, disabling attach."""
    client = _ProxyStubClient([])
    orch = DockerOrchestrator(client=client, proxy_container="")
    assert orch._proxy_container is None
