"""Unit tests for metrics collector logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.containers.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_MANAGED_VALUE,
    VELA_OWNER_LABEL,
)
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus, HealthStatus
from app.core.models import ContainerInfo
from app.core.monitoring.metrics_collector import (
    _positive_int_setting,
    collect_and_store_once,
    cleanup_expired_metrics,
)
from app.db.models import ContainerMetric


@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def seeded_orchestrator(test_user_id: uuid.UUID) -> FakeContainerOrchestrator:
    orch = FakeContainerOrchestrator()
    labels = {
        VELA_MANAGED_LABEL: VELA_MANAGED_VALUE,
        VELA_OWNER_LABEL: str(test_user_id),
    }
    orch.seed_container(
        ContainerInfo(
            id="cid-metrics",
            name="metrics-test",
            image="nginx:alpine",
            status=ContainerStatus.RUNNING,
            created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            ports=[],
            labels=labels,
            health=HealthStatus.NONE,
        )
    )
    orch.register_image("nginx:alpine")
    return orch


async def test_collect_and_store_once_inserts_row(
    db_session_factory, seeded_orchestrator: FakeContainerOrchestrator
) -> None:
    async with db_session_factory() as session:
        await collect_and_store_once(seeded_orchestrator, session)

        result = await session.execute(
            select(ContainerMetric).where(
                ContainerMetric.container_id == "cid-metrics"
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.cpu_percent >= 0.0
        assert row.memory_usage_bytes >= 0
        assert row.memory_limit_bytes >= 0


async def test_collect_and_store_once_skips_non_vela_containers(
    db_session_factory,
) -> None:
    orch = FakeContainerOrchestrator()
    orch.seed_container(
        ContainerInfo(
            id="cid-external",
            name="external",
            image="nginx:alpine",
            status=ContainerStatus.RUNNING,
            created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            ports=[],
            labels={},
            health=HealthStatus.NONE,
        )
    )
    orch.register_image("nginx:alpine")

    async with db_session_factory() as session:
        await collect_and_store_once(orch, session)

        result = await session.execute(select(ContainerMetric))
        assert result.scalars().all() == []


async def test_cleanup_expired_metrics_removes_old_rows(
    db_session_factory,
) -> None:
    async with db_session_factory() as session:
        old_ts = datetime.now(timezone.utc) - timedelta(days=60)
        session.add(
            ContainerMetric(
                container_id="cid-old",
                timestamp=old_ts,
                cpu_percent=10.0,
                memory_usage_bytes=1024,
                memory_limit_bytes=2048,
                memory_percent=50.0,
                network_rx_bytes=0,
                network_tx_bytes=0,
            )
        )
        session.add(
            ContainerMetric(
                container_id="cid-recent",
                timestamp=datetime.now(timezone.utc),
                cpu_percent=20.0,
                memory_usage_bytes=2048,
                memory_limit_bytes=4096,
                memory_percent=50.0,
                network_rx_bytes=0,
                network_tx_bytes=0,
            )
        )
        await session.commit()

        await cleanup_expired_metrics(session)

        result = await session.execute(
            select(ContainerMetric).where(
                ContainerMetric.container_id == "cid-old"
            )
        )
        assert result.scalars().all() == []

        result = await session.execute(
            select(ContainerMetric).where(
                ContainerMetric.container_id == "cid-recent"
            )
        )
        assert len(result.scalars().all()) == 1


def test_positive_int_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    setting_name = "VELA_TEST_METRIC_SETTING"

    monkeypatch.setenv(setting_name, "not-an-int")
    with pytest.raises(ValueError, match=setting_name):
        _positive_int_setting(setting_name, "30")

    for bad_value in ("0", " 0 ", "-30"):
        monkeypatch.setenv(setting_name, bad_value)
        with pytest.raises(ValueError, match=setting_name):
            _positive_int_setting(setting_name, "30")

    monkeypatch.setenv(setting_name, " 5 ")
    assert _positive_int_setting(setting_name, "30") == 5

    monkeypatch.delenv(setting_name, raising=False)
    assert _positive_int_setting(setting_name, "30") == 30
