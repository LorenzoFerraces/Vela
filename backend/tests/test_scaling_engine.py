"""Tests for auto-scaling replica deployment."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus
from app.core.models import ContainerInfo, VolumeMount
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
