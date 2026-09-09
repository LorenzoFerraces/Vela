"""Integration tests for metrics API endpoints."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.containers.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_MANAGED_VALUE,
    VELA_OWNER_LABEL,
    VELA_PROJECT_LABEL,
)
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus, HealthStatus
from app.core.models import ContainerInfo
from app.db.models import (
    ContainerMetric,
    Organization,
    Project,
    ProjectMembership,
)


def _seed_metrics(
    db_session_factory, container_id: str, count: int = 10
) -> None:
    async def _run() -> None:
        async with db_session_factory() as session:
            now = datetime.now(timezone.utc)
            for i in range(count):
                session.add(
                    ContainerMetric(
                        container_id=container_id,
                        timestamp=now - timedelta(minutes=30 * i),
                        cpu_percent=10.0 + i,
                        memory_usage_bytes=1000 * (i + 1),
                        memory_limit_bytes=4096,
                        memory_percent=25.0 + i,
                        network_rx_bytes=500 * (i + 1),
                        network_tx_bytes=200 * (i + 1),
                    )
                )
            await session.commit()

    asyncio.run(_run())


def _seed_container(
    fake_orchestrator: FakeContainerOrchestrator,
    container_id: str,
    name: str,
    test_user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    status: ContainerStatus = ContainerStatus.RUNNING,
) -> None:
    labels = {
        VELA_MANAGED_LABEL: VELA_MANAGED_VALUE,
        VELA_OWNER_LABEL: str(test_user_id),
    }
    if project_id is not None:
        labels[VELA_PROJECT_LABEL] = str(project_id)
    fake_orchestrator.seed_container(
        ContainerInfo(
            id=container_id,
            name=name,
            image="nginx:alpine",
            status=status,
            created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            ports=[],
            labels=labels,
            health=HealthStatus.NONE,
        )
    )
    fake_orchestrator.register_image("nginx:alpine")


def _make_team_project(
    db_session_factory, user_id: uuid.UUID
) -> uuid.UUID:
    """Create organization + shared project + owner membership at the DB level."""

    async def _run() -> uuid.UUID:
        async with db_session_factory() as session:
            org = Organization(name="Widgets Inc")
            session.add(org)
            await session.flush()
            project = Project(
                organization_id=org.id, name="web-frontend", is_personal=False
            )
            session.add(project)
            await session.flush()
            session.add(
                ProjectMembership(
                    project_id=project.id, user_id=user_id, role="owner"
                )
            )
            await session.commit()
            return project.id

    return asyncio.run(_run())


def test_get_metrics_returns_points(
    api_client: TestClient,
    db_session_factory,
) -> None:
    _seed_metrics(db_session_factory, "cid-1", count=5)

    resp = api_client.get("/api/metrics", params={"container_id": "cid-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 5
    assert "timestamp" in data[0]
    assert "cpu_percent" in data[0]


def test_get_metrics_respects_limit(
    api_client: TestClient,
    db_session_factory,
) -> None:
    _seed_metrics(db_session_factory, "cid-1", count=20)

    resp = api_client.get(
        "/api/metrics", params={"container_id": "cid-1", "limit": 5}
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 5


def test_get_metrics_returns_empty_for_no_data(
    api_client: TestClient,
) -> None:
    resp = api_client.get(
        "/api/metrics", params={"container_id": "cid-1"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_metrics_unauthorized(
    anonymous_client: TestClient,
) -> None:
    resp = anonymous_client.get(
        "/api/metrics", params={"container_id": "cid-1"}
    )
    assert resp.status_code == 401


def test_get_metrics_summary_returns_buckets(
    api_client: TestClient,
    db_session_factory,
) -> None:
    _seed_metrics(db_session_factory, "cid-1", count=30)

    resp = api_client.get(
        "/api/metrics/summary", params={"container_id": "cid-1", "hours": 24}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "bucket_start" in data[0]
    assert "cpu_avg" in data[0]
    assert "cpu_max" in data[0]
    assert "memory_usage_avg" in data[0]


def test_get_usage_groups_by_project(
    api_client: TestClient,
    db_session_factory,
    fake_orchestrator: FakeContainerOrchestrator,
    test_user_id: uuid.UUID,
) -> None:
    project_id = _make_team_project(db_session_factory, test_user_id)
    _seed_container(
        fake_orchestrator, "cid-team", "team-web", test_user_id,
        project_id=project_id,
    )
    _seed_metrics(db_session_factory, "cid-1", count=2)
    _seed_metrics(db_session_factory, "cid-team", count=2)

    resp = api_client.get("/api/metrics/usage")
    assert resp.status_code == 200
    data = resp.json()

    # cid-1 (no project label) -> personal group; cid-team -> team project group
    assert len(data["projects"]) == 2
    team = next(
        p for p in data["projects"] if p["project_name"] == "web-frontend"
    )
    assert team["project_id"] == str(project_id)
    assert team["team_name"] == "Widgets Inc"
    # latest row is i=0 (newest timestamp): cpu 10.0, memory 1000
    assert team["cpu_percent_total"] == 10.0
    assert team["memory_usage_bytes_total"] == 1000
    personal = next(p for p in data["projects"] if p["project_id"] is None)
    assert personal["cpu_percent_total"] == 10.0
    assert personal["memory_usage_bytes_total"] == 1000
    assert data["total_cpu_percent"] == 20.0
    assert data["total_memory_usage_bytes"] == 2000
    assert data["running_containers"] == 2


def test_get_usage_stopped_container_reports_no_usage(
    api_client: TestClient,
    db_session_factory,
    fake_orchestrator: FakeContainerOrchestrator,
    test_user_id: uuid.UUID,
) -> None:
    _seed_container(
        fake_orchestrator, "cid-stopped", "stopped-app", test_user_id,
        status=ContainerStatus.STOPPED,
    )
    _seed_metrics(db_session_factory, "cid-stopped", count=1)  # stale row

    resp = api_client.get("/api/metrics/usage")
    assert resp.status_code == 200
    data = resp.json()
    entry = next(
        e
        for p in data["projects"]
        for e in p["containers"]
        if e["container_id"] == "cid-stopped"
    )
    assert entry["cpu_percent"] is None
    assert entry["memory_usage_bytes"] is None
    assert entry["memory_percent"] is None
    # only the fixture's cid-1 is running
    assert data["running_containers"] == 1
    assert data["total_memory_usage_bytes"] == 0


def test_get_usage_unauthorized(
    anonymous_client: TestClient,
) -> None:
    resp = anonymous_client.get("/api/metrics/usage")
    assert resp.status_code == 401
