"""Tests for mapping Docker list/inspect payloads to ContainerInfo."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.enums import ContainerStatus, HealthStatus
from app.core.containers.docker_orchestrator import (
    _inspect_to_container_info,
    _parse_created,
    _ports_from_list,
)


def test_inspect_to_container_info_maps_list_payload() -> None:
    created_unix = 1735689600  # 2025-01-01T00:00:00Z
    data = {
        "Id": "abc123def456",
        "Names": ["/vela-web"],
        "Image": "nginx:latest",
        "Labels": {"vela.managed": "true", "vela.owner_id": "u1"},
        "Created": created_unix,
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Ports": [
            {"IP": "0.0.0.0", "PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"},
            {"PrivatePort": 443, "Type": "tcp"},
        ],
    }
    info = _inspect_to_container_info(data)
    assert info.id == "abc123def456"
    assert info.name == "vela-web"
    assert info.image == "nginx:latest"
    assert info.labels == {"vela.managed": "true", "vela.owner_id": "u1"}
    assert info.status is ContainerStatus.RUNNING
    assert info.health is HealthStatus.HEALTHY
    assert info.created_at == datetime.fromtimestamp(created_unix, tz=timezone.utc)
    assert info.created_at.tzinfo is not None
    assert len(info.ports) == 1
    assert info.ports[0].host_port == 8080
    assert info.ports[0].container_port == 80
    assert info.ports[0].protocol == "tcp"
    assert info.volumes == []


def test_inspect_to_container_info_maps_inspect_payload() -> None:
    data = {
        "Id": "abc123def456",
        "Name": "/vela-web",
        "Image": "sha256:0123456789abcdef",
        "Created": "2025-01-01T00:00:00.123456Z",
        "State": {"Status": "running"},
        "Config": {
            "Image": "nginx:latest",
            "Labels": {"vela.managed": "true"},
        },
        "NetworkSettings": {
            "Ports": {
                "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],
                "443/tcp": None,
            },
        },
        "Mounts": [
            {"Type": "bind", "Source": "/host/data", "Destination": "/app/data"},
        ],
    }
    info = _inspect_to_container_info(data)
    assert info.id == "abc123def456"
    assert info.name == "vela-web"
    assert info.image == "nginx:latest"
    assert info.labels == {"vela.managed": "true"}
    assert info.status is ContainerStatus.RUNNING
    assert info.health is HealthStatus.NONE
    assert info.created_at == _parse_created("2025-01-01T00:00:00.123456Z")
    assert len(info.ports) == 1
    assert info.ports[0].host_port == 8080
    assert info.ports[0].container_port == 80
    assert info.ports[0].protocol == "tcp"
    assert len(info.volumes) == 1
    assert info.volumes[0].source == "/host/data"
    assert info.volumes[0].target == "/app/data"


def test_ports_from_list_skips_unbound_entries() -> None:
    data = {
        "Ports": [
            {"IP": "0.0.0.0", "PrivatePort": 3000, "PublicPort": 3000, "Type": "tcp"},
            {"PrivatePort": 3001, "Type": "tcp"},
        ]
    }
    ports = _ports_from_list(data)
    assert len(ports) == 1
    assert ports[0].host_port == 3000
    assert ports[0].container_port == 3000
    assert ports[0].protocol == "tcp"


def test_ports_from_list_empty() -> None:
    assert _ports_from_list({}) == []
    assert _ports_from_list({"Ports": []}) == []
