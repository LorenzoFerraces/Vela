"""Unit tests for Traefik route wiring helpers."""

from __future__ import annotations

from app.api.route_wiring import backend_port_for_route
from app.core.models import DeployConfig, PortMapping


def test_backend_port_uses_first_mapping_when_host_ports_published() -> None:
    cfg = DeployConfig(
        image="nginx:alpine",
        ports=[PortMapping(host_port=8080, container_port=3000)],
        container_listen_port=80,
    )
    assert backend_port_for_route(cfg) == 3000


def test_backend_port_falls_back_to_listen_port_without_mappings() -> None:
    cfg = DeployConfig(image="vela/gitbuild:x", container_listen_port=5173)
    assert backend_port_for_route(cfg) == 5173
