"""Tests for default-network auto-creation at deploy time."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.core.containers.docker_orchestrator import DockerOrchestrator


class _StubNetworks:
    def __init__(self, names: list[str]) -> None:
        self._names = list(names)
        self.created: list[str] = []

    def list(self, filters: dict[str, Any] | None = None) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=n) for n in self._names]

    def create(self, name: str, driver: str = "bridge") -> None:
        self.created.append(name)
        self._names.append(name)


class _StubClient:
    def __init__(self, names: list[str]) -> None:
        self.networks = _StubNetworks(names)


def _orchestrator(names: list[str]) -> tuple[DockerOrchestrator, _StubNetworks]:
    client = _StubClient(names)
    orch = DockerOrchestrator.__new__(DockerOrchestrator)
    orch._client = client
    orch._default_network = "vela-workloads"
    orch._default_network_ensured = False
    return orch, client.networks


def test_ensure_default_network_creates_missing_network() -> None:
    orch, networks = _orchestrator([])
    orch._ensure_default_network_sync()
    assert networks.created == ["vela-workloads"]
    assert orch._default_network_ensured is True


def test_ensure_default_network_skips_existing() -> None:
    orch, networks = _orchestrator(["vela-workloads"])
    orch._ensure_default_network_sync()
    assert networks.created == []


def test_ensure_default_network_runs_once() -> None:
    orch, networks = _orchestrator([])
    orch._ensure_default_network_sync()
    orch._ensure_default_network_sync()
    assert networks.created == ["vela-workloads"]
