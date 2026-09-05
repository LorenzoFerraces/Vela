"""Tests for auto-scaling replica deployment."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus
from app.core.models import ContainerInfo, VolumeMount
from app.core.scaling.models import ScalingPolicy
from app.core.scaling.scaling_engine import _scale_up
from app.core.traffic.traffic_models import BackendServer, RouteSpec
from app.core.traffic.traffic_router import NoopTrafficRouter


async def test_scale_up_copies_base_container_volumes() -> None:
    base_name = "vela-app"
    base_volumes = [
        VolumeMount(source="/data/uploads/abc123", target="/app/data"),
    ]
    base_info = ContainerInfo(
        id="base-id",
        name=base_name,
        image="myapp:latest",
        status=ContainerStatus.RUNNING,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
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

    await _scale_up(
        orchestrator,
        traffic_router,
        base_name,
        base_port=8080,
        base_spec=base_spec,
        current_replica_count=0,
    )

    assert orchestrator.last_deploy_config is not None
    assert orchestrator.last_deploy_config.name == f"{base_name}-r1"
    assert orchestrator.last_deploy_config.volumes == base_volumes


def test_scaling_policy_min_equal_to_max_is_accepted() -> None:
    policy = ScalingPolicy(
        user_id="u1", target_cpu_min=70.0, max_instances=3, min_instances=3
    )
    assert policy.min_instances == 3


def test_scaling_policy_min_greater_than_max_raises() -> None:
    with pytest.raises(ValidationError):
        ScalingPolicy(
            user_id="u1", target_cpu_min=70.0, max_instances=2, min_instances=3
        )


def test_scaling_policy_min_instances_zero_raises() -> None:
    with pytest.raises(ValidationError):
        ScalingPolicy(
            user_id="u1", target_cpu_min=70.0, max_instances=2, min_instances=0
        )
