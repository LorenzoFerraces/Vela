"""Unit tests for Pydantic domain models in ``app.core.models``."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.enums import (
    BuildStrategy,
    ContainerStatus,
    HealthStatus,
    RestartPolicy,
    SupportedLanguage,
)
from app.core.models import (
    BuildResult,
    ContainerInfo,
    ContainerStats,
    DeployConfig,
    HealthCheckConfig,
    HealthResult,
    PortMapping,
    ProjectInfo,
    ProjectSource,
)


def test_port_mapping_defaults_and_roundtrip() -> None:
    pm = PortMapping(host_port=8080, container_port=80)
    assert pm.protocol == "tcp"
    data = pm.model_dump()
    assert data == {"host_port": 8080, "container_port": 80, "protocol": "tcp"}
    assert PortMapping.model_validate(data) == pm


def test_health_check_config_defaults() -> None:
    hc = HealthCheckConfig(command=["curl", "-f", "http://localhost/"])
    assert hc.interval_s == 30
    assert hc.timeout_s == 5
    assert hc.retries == 3
    assert hc.start_period_s == 0


def test_deploy_config_minimal() -> None:
    d = DeployConfig(image="nginx:alpine")
    assert d.name is None
    assert d.env_vars == {}
    assert d.ports == []
    assert d.restart_policy is RestartPolicy.NEVER
    assert d.health_check is None
    assert d.route_host is None
    assert d.route_path_prefix == "/"
    assert d.route_tls is False
    assert d.public_route is False


def test_deploy_config_route_path_prefix_validation() -> None:
    with pytest.raises(ValidationError):
        DeployConfig(
            image="nginx:alpine",
            route_host="app.test",
            route_path_prefix="api",
        )


def test_deploy_config_rejects_missing_image() -> None:
    with pytest.raises(ValidationError) as exc:
        DeployConfig.model_validate({})
    assert "image" in str(exc.value).lower()


def test_deploy_config_nested_ports_and_restart_from_string() -> None:
    d = DeployConfig.model_validate(
        {
            "image": "redis:7",
            "name": "cache",
            "ports": [{"host_port": 6379, "container_port": 6379}],
            "restart_policy": "unless_stopped",
        }
    )
    assert len(d.ports) == 1
    assert d.ports[0].protocol == "tcp"
    assert d.restart_policy is RestartPolicy.UNLESS_STOPPED


def test_container_info_enums_coerce_from_string() -> None:
    created = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)
    info = ContainerInfo.model_validate(
        {
            "id": "abc123",
            "name": "web",
            "image": "nginx:latest",
            "status": "running",
            "created_at": created.isoformat(),
            "health": "healthy",
        }
    )
    assert info.status is ContainerStatus.RUNNING
    assert info.health is HealthStatus.HEALTHY


def test_container_stats_network_defaults_zero() -> None:
    ts = datetime.now(timezone.utc)
    stats = ContainerStats(
        container_id="x",
        timestamp=ts,
        cpu_percent=12.5,
        memory_usage_bytes=128_000_000,
        memory_limit_bytes=256_000_000,
        memory_percent=50.0,
    )
    assert stats.network_rx_bytes == 0
    assert stats.network_tx_bytes == 0


def test_health_result_optional_fields() -> None:
    ts = datetime.now(timezone.utc)
    hr = HealthResult(status=HealthStatus.STARTING, timestamp=ts)
    assert hr.output is None
    assert hr.exit_code is None


def test_project_source_branch_default() -> None:
    src = ProjectSource(git_url="https://example.com/repo.git")
    assert src.branch == "main"
    assert src.local_path is None


def test_project_info_minimal() -> None:
    pi = ProjectInfo(language=SupportedLanguage.PYTHON)
    assert pi.has_dockerfile is False
    assert pi.framework is None


def test_build_result_nested_project_info() -> None:
    pi = ProjectInfo(
        language=SupportedLanguage.TYPESCRIPT,
        framework="vite",
        has_dockerfile=True,
    )
    br = BuildResult(
        image_id="sha256:deadbeef",
        image_tag="myapp:latest",
        strategy=BuildStrategy.DOCKERFILE_EXISTS,
        build_log="Step 1/5\n",
        project_info=pi,
    )
    assert br.project_info.language is SupportedLanguage.TYPESCRIPT
    assert br.strategy is BuildStrategy.DOCKERFILE_EXISTS
