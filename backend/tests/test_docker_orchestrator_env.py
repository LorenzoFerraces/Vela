"""Tests for container environment merging (Vite behind Traefik)."""

from __future__ import annotations

from app.core.docker_orchestrator import DockerOrchestrator
from app.core.models import DeployConfig


def test_container_env_sets_vite_allowed_hosts_from_route_host() -> None:
    orch = DockerOrchestrator.__new__(DockerOrchestrator)
    cfg = DeployConfig(
        image="test:latest",
        route_host="vela-abc.example.com",
    )
    env = orch._container_env(cfg)
    assert env["__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"] == "vela-abc.example.com"


def test_container_env_respects_existing_vite_allowed_hosts() -> None:
    orch = DockerOrchestrator.__new__(DockerOrchestrator)
    cfg = DeployConfig(
        image="test:latest",
        route_host="a.example.com",
        env_vars={"__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS": ".custom.test"},
    )
    env = orch._container_env(cfg)
    assert env["__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"] == ".custom.test"


def test_container_env_no_route_skips_vite_var() -> None:
    orch = DockerOrchestrator.__new__(DockerOrchestrator)
    cfg = DeployConfig(image="test:latest")
    env = orch._container_env(cfg)
    assert "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS" not in env
