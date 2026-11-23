"""Tests for auto-scaling replica deployment."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.containers.docker_orchestrator import VELA_PROJECT_LABEL
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus, ScalingMetric
from app.core.models import ContainerInfo, DeployConfig, VolumeMount
from app.core.monitoring import edge_requests
from app.core.scaling import scaling_engine
from app.core.scaling.models import ScalingPolicy
from app.core.scaling.scaling_engine import _evaluate_policy, _measure_metric, _scale_up
from app.core.traffic.traffic_models import BackendServer, RouteSpec
from app.core.traffic.traffic_router import NoopTrafficRouter


async def test_scale_up_copies_base_container_volumes(db_session_factory) -> None:
    base_name = "vela-app"
    base_volumes = [
        VolumeMount(source="/data/uploads/abc123", target="/app/data"),
    ]
    base_info = ContainerInfo(
        id="base-id",
        name=base_name,
        image="myapp:latest",
        status=ContainerStatus.RUNNING,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        volumes=base_volumes,
        labels={"vela.managed": "true"},
    )
    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(base_info)
    orchestrator.register_image("myapp:latest")

    traffic_router = NoopTrafficRouter()
    base_spec = RouteSpec(
        route_id=base_name,
        host="app.example.com",
        path_prefix="/",
        backend_servers=[BackendServer(host=base_name, port=8080)],
    )
    await traffic_router.upsert_route(base_spec)

    base_config = DeployConfig(
        image="myapp:latest", name=base_name, volumes=base_volumes
    )
    async with db_session_factory() as session:
        scaled_up = await _scale_up(
            orchestrator,
            traffic_router,
            base_name,
            base_port=8080,
            base_spec=base_spec,
            current_replica_count=0,
            base_config=base_config,
            session=session,
        )

    assert scaled_up is True
    assert orchestrator.last_deploy_config is not None
    assert orchestrator.last_deploy_config.name == f"{base_name}-r1"
    assert orchestrator.last_deploy_config.volumes == base_volumes


async def test_scale_up_blocked_when_team_compute_quota_full(
    db_session_factory, caplog,
) -> None:
    """A full team compute quota stops deployment with a quiet warning, no traceback."""
    from app.db.models import Organization, Project

    async with db_session_factory() as session:
        organization = Organization(name="quota org")
        session.add(organization)
        await session.flush()
        project = Project(
            organization_id=organization.id,
            name="quota team",
            max_running_containers=1,
        )
        session.add(project)
        await session.commit()

        orchestrator = FakeContainerOrchestrator()
        orchestrator.seed_container(
            ContainerInfo(
                id="running-base",
                name="vela-app",
                image="myapp:latest",
                status=ContainerStatus.RUNNING,
                created_at=datetime(2026, 6, 1, tzinfo=UTC),
                labels={VELA_PROJECT_LABEL: str(project.id)},
            )
        )
        traffic_router = NoopTrafficRouter()
        base_spec = RouteSpec(
            route_id="vela-app",
            host="app.example.com",
            path_prefix="/",
            backend_servers=[BackendServer(host="vela-app", port=8080)],
        )
        await traffic_router.upsert_route(base_spec)

        with caplog.at_level(logging.WARNING):
            scaled_up = await _scale_up(
                orchestrator,
                traffic_router,
                "vela-app",
                base_port=8080,
                base_spec=base_spec,
                current_replica_count=0,
                base_config=DeployConfig(
                    image="myapp:latest", name="vela-app", project_id=project.id
                ),
                session=session,
            )

    assert scaled_up is False
    assert orchestrator.last_deploy_config is None
    assert "compute quota" in caplog.text.lower()
    assert "Traceback" not in caplog.text


async def test_failed_scale_up_does_not_record_scale_event(
    db_session_factory, monkeypatch
) -> None:
    from app.core.deploy import deployment_history
    from app.core.models import ScalingPolicyInfo
    from app.core.scaling.policy_repository import ScalingPolicyRuntime

    now = datetime.now(UTC)
    runtime = ScalingPolicyRuntime(
        policy=ScalingPolicyInfo(
            id=uuid.uuid4(), container_name="web", enabled=True,
            min_replicas=1, max_replicas=3, metric=ScalingMetric.CPU_PERCENT,
            scale_up_threshold=50.0, scale_down_threshold=10.0,
            cooldown_seconds=0, scale_up_stabilization_seconds=0,
            scale_down_stabilization_seconds=0, last_scaled_at=None,
            created_at=now, updated_at=now,
        ),
        scale_up_condition_since=now - timedelta(seconds=5),
        scale_down_condition_since=None,
    )
    base_spec = RouteSpec(
        route_id="web", host="web.example", path_prefix="/",
        backend_servers=[BackendServer(host="web", port=80)],
    )
    monkeypatch.setattr(
        scaling_engine, "_base_container_info",
        AsyncMock(return_value=SimpleNamespace(id="base-id")),
    )
    monkeypatch.setattr(
        deployment_history, "load_deploy_config_snapshot",
        AsyncMock(return_value=DeployConfig(image="nginx", name="web")),
    )
    monkeypatch.setattr(scaling_engine, "_measure_metric", AsyncMock(return_value=90.0))
    monkeypatch.setattr(scaling_engine, "_collect_replica_configs", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        scaling_engine, "_build_route_spec_for_service", AsyncMock(return_value=base_spec)
    )
    fake_scale_up = AsyncMock(return_value=False)
    fake_record = AsyncMock()
    monkeypatch.setattr(scaling_engine, "_scale_up", fake_scale_up)
    monkeypatch.setattr(scaling_engine, "record_scale_event", fake_record)

    async with db_session_factory() as session:
        await _evaluate_policy(session, AsyncMock(), AsyncMock(), runtime)

    fake_scale_up.assert_awaited_once()
    fake_record.assert_not_awaited()

    fake_scale_up.return_value = True
    async with db_session_factory() as session:
        await _evaluate_policy(session, AsyncMock(), AsyncMock(), runtime)

    fake_record.assert_awaited_once()


def test_scaling_policy_min_equal_to_max_is_accepted() -> None:
    """min_instances equal to max_instances is a valid policy."""
    policy = ScalingPolicy(
        user_id="u1", target_cpu_min=70.0, max_instances=3, min_instances=3
    )
    assert policy.min_instances == 3


def test_scaling_policy_min_greater_than_max_raises() -> None:
    """min_instances above max_instances fails validation."""
    with pytest.raises(ValidationError):
        ScalingPolicy(
            user_id="u1", target_cpu_min=70.0, max_instances=2, min_instances=3
        )


def test_scaling_policy_min_instances_zero_raises() -> None:
    """min_instances of zero fails validation."""
    with pytest.raises(ValidationError):
        ScalingPolicy(
            user_id="u1", target_cpu_min=70.0, max_instances=2, min_instances=0
        )


class _Stats:
    cpu_percent = 42.0


class _Orchestrator:
    async def get_stats(self, name: str) -> _Stats:
        return _Stats()


class _EdgeRouter:
    async def get_route(self, name: str) -> object:
        return SimpleNamespace(host="web.example")


def test_noop_router_keeps_cpu_proxy() -> None:
    result = asyncio.run(_measure_metric(
        _Orchestrator(), "web", ScalingMetric.REQUESTS_PER_SECOND, NoopTrafficRouter(),  # type: ignore[arg-type]
    ))
    assert result == 42.0


def test_rps_uses_edge_counter(monkeypatch) -> None:
    monkeypatch.setattr(
        edge_requests, "get_edge_request_rates",
        lambda: edge_requests.EdgeRequestRates({"web.example": 12.0}, True),
    )
    result = asyncio.run(_measure_metric(
        _Orchestrator(), "web", ScalingMetric.REQUESTS_PER_SECOND, _EdgeRouter(),  # type: ignore[arg-type]
    ))
    assert result == 12.0


def test_rps_fails_closed_when_signal_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        edge_requests, "get_edge_request_rates",
        lambda: edge_requests.EdgeRequestRates({}, False),
    )
    result = asyncio.run(_measure_metric(
        _Orchestrator(), "web", ScalingMetric.REQUESTS_PER_SECOND, _EdgeRouter(),  # type: ignore[arg-type]
    ))
    assert result is None


def test_rps_idle_routed_host_is_zero_when_signal_flowing(monkeypatch) -> None:
    monkeypatch.setattr(
        edge_requests, "get_edge_request_rates",
        lambda: edge_requests.EdgeRequestRates({"other.example": 5.0}, True),
    )
    result = asyncio.run(_measure_metric(
        _Orchestrator(), "web", ScalingMetric.REQUESTS_PER_SECOND, _EdgeRouter(),  # type: ignore[arg-type]
    ))
    assert result == 0.0


def test_rps_empty_rate_map_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        edge_requests, "get_edge_request_rates",
        lambda: edge_requests.EdgeRequestRates({}, True),
    )
    result = asyncio.run(_measure_metric(
        _Orchestrator(), "web", ScalingMetric.REQUESTS_PER_SECOND, _EdgeRouter(),  # type: ignore[arg-type]
    ))
    assert result is None
