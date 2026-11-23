"""Integration tests for the team showback API and CSV export."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.auth.enums import UserRole
from app.core.containers.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_MANAGED_VALUE,
    VELA_OWNER_LABEL,
    VELA_PROJECT_LABEL,
)
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus, HealthStatus
from app.core.models import ContainerInfo
from app.core.monitoring.metrics_collector import METRICS_INTERVAL_SECONDS
from app.db.models import ContainerMetric, DeploymentRecord, Project, User


def _seed_team_container(
    fake_orchestrator: FakeContainerOrchestrator,
    container_id: str,
    owner_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    disk_bytes: int = 0,
) -> None:
    fake_orchestrator.seed_container(ContainerInfo(
        id=container_id,
        name=container_id,
        image="nginx:alpine",
        status=ContainerStatus.RUNNING,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        ports=[],
        labels={
            VELA_MANAGED_LABEL: VELA_MANAGED_VALUE,
            VELA_OWNER_LABEL: str(owner_id),
            VELA_PROJECT_LABEL: str(project_id),
        },
        health=HealthStatus.NONE,
        disk_bytes=disk_bytes,
    ))


def _seed_metric(
    db_session_factory,
    container_id: str,
    *,
    when: datetime | None = None,
    cpu_percent: float = 50.0,
    memory_bytes: int = 1024**3,
) -> None:
    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(ContainerMetric(
                container_id=container_id,
                timestamp=when or datetime.now(UTC),
                cpu_percent=cpu_percent,
                memory_usage_bytes=memory_bytes,
                memory_limit_bytes=2 * 1024**3,
                memory_percent=50.0,
                network_rx_bytes=0,
                network_tx_bytes=0,
            ))
            await session.commit()

    asyncio.run(seed())


def test_showback_is_team_scoped_and_reports_resource_time(api_client: TestClient):
    response = api_client.get("/api/metrics/showback")
    assert response.status_code == 200
    body = response.json()
    assert "teams" in body
    for team in body["teams"]:
        assert set(team) >= {"team_name", "cpu_seconds", "memory_gib_hours", "storage_gib_days"}
        assert team["cost_currency"] is None


def test_showback_is_401_for_anonymous(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/api/metrics/showback").status_code == 401


def test_csv_export_has_expected_header(api_client: TestClient) -> None:
    # The SPA passes the month the showback endpoint derived for it.
    month = api_client.get("/api/metrics/showback").json()["month"]
    response = api_client.get(f"/api/metrics/showback/export?month={month}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0] == "team,cpu_seconds,memory_gib_hours,storage_gib_days"


def test_csv_export_rejects_invalid_month(api_client: TestClient) -> None:
    assert api_client.get("/api/metrics/showback/export?month=not-a-month").status_code == 422


def test_showback_scopes_metrics_to_caller_team_and_widens_for_admin(
    api_client: TestClient,
    db_session_factory,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
    seeded_other_user: User,
) -> None:
    """A team member sees only their own container's resource-time; an admin sees both."""
    async def seed() -> tuple[uuid.UUID, uuid.UUID]:
        async with db_session_factory() as session:
            caller = await session.get(User, seeded_user.id)
            other = await session.get(User, seeded_other_user.id)
            caller_project = await session.get(Project, caller.personal_project_id)
            other_project = await session.get(Project, other.personal_project_id)
            caller_project.name = "Team Alpha"
            other_project.name = "Team Beta"
            now = datetime.now(UTC)
            session.add(ContainerMetric(
                container_id="cid-alpha", timestamp=now, cpu_percent=50.0,
                memory_usage_bytes=1024**3, memory_limit_bytes=2 * 1024**3,
                memory_percent=50.0, network_rx_bytes=0, network_tx_bytes=0,
            ))
            session.add(ContainerMetric(
                container_id="cid-beta", timestamp=now, cpu_percent=100.0,
                memory_usage_bytes=2 * 1024**3, memory_limit_bytes=4 * 1024**3,
                memory_percent=50.0, network_rx_bytes=0, network_tx_bytes=0,
            ))
            await session.commit()
            return caller.personal_project_id, other.personal_project_id

    caller_project_id, other_project_id = asyncio.run(seed())
    _seed_team_container(fake_orchestrator, "cid-alpha", seeded_user.id, caller_project_id)
    _seed_team_container(fake_orchestrator, "cid-beta", seeded_other_user.id, other_project_id)

    caller_teams = {
        team["team_name"]: team
        for team in api_client.get("/api/metrics/showback").json()["teams"]
    }
    assert set(caller_teams) == {"Team Alpha"}
    assert caller_teams["Team Alpha"]["cpu_seconds"] == pytest.approx(
        0.5 * METRICS_INTERVAL_SECONDS
    )

    async def promote_caller_to_admin() -> None:
        async with db_session_factory() as session:
            user = await session.get(User, seeded_user.id)
            user.role = UserRole.ADMIN
            await session.commit()

    asyncio.run(promote_caller_to_admin())
    admin_teams = {
        team["team_name"]: team
        for team in api_client.get("/api/metrics/showback").json()["teams"]
    }
    assert {"Team Alpha", "Team Beta"} <= set(admin_teams)
    assert admin_teams["Team Alpha"]["cpu_seconds"] == pytest.approx(
        0.5 * METRICS_INTERVAL_SECONDS
    )
    assert admin_teams["Team Beta"]["cpu_seconds"] == pytest.approx(
        1.0 * METRICS_INTERVAL_SECONDS
    )


def test_showback_sums_all_samples_and_reports_storage(
    api_client: TestClient,
    db_session_factory,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
    seeded_other_user: User,
) -> None:
    async def seed() -> tuple[uuid.UUID, uuid.UUID]:
        async with db_session_factory() as session:
            caller = await session.get(User, seeded_user.id)
            other = await session.get(User, seeded_other_user.id)
            caller_project = await session.get(Project, caller.personal_project_id)
            other_project = await session.get(Project, other.personal_project_id)
            caller_project.name = "Team Alpha"
            other_project.name = "Team Beta"
            caller.role = UserRole.ADMIN
            await session.commit()
            return caller.personal_project_id, other.personal_project_id

    caller_project_id, other_project_id = asyncio.run(seed())
    now = datetime.now(UTC)
    _seed_metric(db_session_factory, "cid-alpha", when=now)
    _seed_metric(db_session_factory, "cid-alpha", when=now)
    _seed_team_container(
        fake_orchestrator, "cid-alpha", seeded_user.id, caller_project_id,
        disk_bytes=2 * 1024**3,
    )
    _seed_team_container(
        fake_orchestrator, "cid-beta", seeded_other_user.id, other_project_id
    )

    teams = {
        team["team_name"]: team
        for team in api_client.get("/api/metrics/showback").json()["teams"]
    }
    # Two 50% samples integrate to one full core's worth of time; memory too.
    assert teams["Team Alpha"]["cpu_seconds"] == pytest.approx(
        2 * 0.5 * METRICS_INTERVAL_SECONDS
    )
    assert teams["Team Alpha"]["memory_gib_hours"] == pytest.approx(
        2 * 1 * METRICS_INTERVAL_SECONDS / 3600
    )
    # A project with a container but no samples still reports zero.
    assert teams["Team Beta"]["cpu_seconds"] == 0
    # 2 GiB current disk × 30 days, computed from the shared inventory.
    assert teams["Team Alpha"]["storage_gib_days"] == pytest.approx(60.0)


def test_showback_counts_unlabeled_owner_container(
    api_client: TestClient,
    db_session_factory,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
) -> None:
    _seed_metric(db_session_factory, "cid-unlabeled")
    # No project label: resolve_container_project_id falls back to the owner's
    # personal project, so this container's usage must not vanish.
    fake_orchestrator.seed_container(ContainerInfo(
        id="cid-unlabeled",
        name="cid-unlabeled",
        image="nginx:alpine",
        status=ContainerStatus.RUNNING,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        ports=[],
        labels={
            VELA_MANAGED_LABEL: VELA_MANAGED_VALUE,
            VELA_OWNER_LABEL: str(seeded_user.id),
        },
        health=HealthStatus.NONE,
    ))

    teams = api_client.get("/api/metrics/showback").json()["teams"]
    assert len(teams) == 1
    assert teams[0]["cpu_seconds"] == pytest.approx(0.5 * METRICS_INTERVAL_SECONDS)


def test_showback_counts_retained_samples_for_departed_container(
    api_client: TestClient,
    db_session_factory,
    seeded_user: User,
) -> None:
    async def seed() -> uuid.UUID:
        async with db_session_factory() as session:
            user = await session.get(User, seeded_user.id)
            session.add(DeploymentRecord(
                user_id=user.id,
                project_id=user.personal_project_id,
                container_id="cid-departed",
                container_name="departed",
                source_kind="image",
                source_ref="nginx:alpine",
                image_tag="nginx:alpine",
                container_port=80,
            ))
            await session.commit()
            return user.personal_project_id

    asyncio.run(seed())
    _seed_metric(db_session_factory, "cid-departed")
    # No orchestrator container exists; the deployment record restores attribution.
    teams = api_client.get("/api/metrics/showback").json()["teams"]
    assert teams[0]["cpu_seconds"] == pytest.approx(0.5 * METRICS_INTERVAL_SECONDS)


def test_export_aggregates_only_requested_month(
    api_client: TestClient,
    db_session_factory,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
) -> None:
    async def project_id() -> uuid.UUID:
        async with db_session_factory() as session:
            user = await session.get(User, seeded_user.id)
            return user.personal_project_id

    caller_project_id = asyncio.run(project_id())
    now = datetime.now(UTC)
    _seed_metric(db_session_factory, "cid-in-month", when=now)
    _seed_metric(
        db_session_factory, "cid-in-month",
        when=now - timedelta(days=40), cpu_percent=100.0,
    )
    _seed_team_container(
        fake_orchestrator, "cid-in-month", seeded_user.id, caller_project_id
    )

    month = now.strftime("%Y-%m")
    response = api_client.get(f"/api/metrics/showback/export?month={month}")
    assert response.status_code == 200
    rows = [line.split(",") for line in response.text.splitlines()[1:]]
    assert float(rows[0][1]) == pytest.approx(0.5 * METRICS_INTERVAL_SECONDS)


def test_export_rejects_months_outside_retention(api_client: TestClient) -> None:
    for month in ("2000-01", "2099-01"):
        response = api_client.get(f"/api/metrics/showback/export?month={month}")
        assert response.status_code == 404
        assert "No retained usage data" in response.text


def test_export_neutralizes_spreadsheet_formulas(
    api_client: TestClient, db_session_factory, seeded_user: User
) -> None:
    async def seed() -> None:
        async with db_session_factory() as session:
            user = await session.get(User, seeded_user.id)
            project = await session.get(Project, user.personal_project_id)
            project.name = "=HYPERLINK(\"http://evil\")"
            await session.commit()

    asyncio.run(seed())
    summary = api_client.get("/api/metrics/showback").json()
    assert summary["teams"][0]["team_name"] == "=HYPERLINK(\"http://evil\")"
    response = api_client.get(
        f"/api/metrics/showback/export?month={summary['month']}"
    )
    assert response.status_code == 200
    assert "'=HYPERLINK" in response.text
