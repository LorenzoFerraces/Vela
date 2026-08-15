# Resource Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Time-series charts of CPU, memory, and network usage per container. Background collector polls Docker stats and stores in Postgres.

**Architecture:** Background worker polls container stats at 30s intervals, stores in `container_metrics` table. API provides raw points and aggregated summaries. Frontend renders charts with recharts.

**Tech Stack:** SQLAlchemy 2.x, Alembic, PostgreSQL, FastAPI, React, recharts, TypeScript

## Global Constraints

- Python 3.12+, TypeScript, exact npm versions (no ^ or ~)
- Backend MVC: core/ (domain), schemas.py (views), routes/ (controllers)
- Domain packages under `app/core/<domain>/` when 3+ modules
- TDD: write failing test first, then minimal implementation
- Metrics collector runs as background asyncio.Task (like container_monitor)
- Configurable retention to prevent unbounded growth
- Use `recharts` for frontend charts (add to package.json)

---

## Task 1: Add `ContainerMetric` ORM model and Alembic migration

**Files:**
- Create: `backend/app/db/models.py` (append `ContainerMetric` class)
- Create: `backend/alembic/versions/0015_container_metrics.py`
- Modify: `backend/tests/conftest.py` (no change needed — `Base.metadata.create_all` auto-picks up new models)

**Interfaces:**
- Produces: `ContainerMetric` ORM model on `Base.metadata`

### 1.1 Add `ContainerMetric` ORM model

- [ ] Append the following class to `backend/app/db/models.py` (after `StackComposition`, before EOF):

```python
class ContainerMetric(Base):
    __tablename__ = "container_metrics"
    __table_args__ = (
        sa.Index("ix_container_metrics_container_timestamp", "container_id", "timestamp", postgresql_using="btree"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    container_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    cpu_percent: Mapped[float] = mapped_column(Float, nullable=False)
    memory_usage_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_limit_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_percent: Mapped[float] = mapped_column(Float, nullable=False)
    network_rx_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    network_tx_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
```

- [ ] Add `import sqlalchemy as sa` at top of `backend/app/db/models.py` if not present (the `sa.Index` needs it). Check existing imports — if `sa` is not aliased, add `import sqlalchemy as sa` alongside existing `from sqlalchemy import ...`.

### 1.2 Create Alembic migration

- [ ] Run: `cd backend && alembic revision -m "container_metrics"` to generate the migration file. The file should be named `0015_container_metrics.py` (rename if alembic auto-generated a different prefix).

- [ ] Write `backend/alembic/versions/0015_container_metrics.py`:

```python
"""Add container_metrics table for time-series resource data.

Revision ID: 0015_container_metrics
Revises: 0014_stacks
Create Date: 2026-08-03
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_container_metrics"
down_revision: str | Sequence[str] | None = "0014_stacks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "container_metrics",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_usage_bytes", sa.Integer(), nullable=False),
        sa.Column("memory_limit_bytes", sa.Integer(), nullable=False),
        sa.Column("memory_percent", sa.Float(), nullable=False),
        sa.Column("network_rx_bytes", sa.Integer(), nullable=False),
        sa.Column("network_tx_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_container_metrics_container_id"),
        "container_metrics",
        ["container_id"],
        unique=False,
    )
    op.create_index(
        "ix_container_metrics_container_timestamp",
        "container_metrics",
        ["container_id", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_container_metrics_container_timestamp", table_name="container_metrics"
    )
    op.drop_index(
        op.f("ix_container_metrics_container_id"), table_name="container_metrics"
    )
    op.drop_table("container_metrics")
```

### 1.3 Verify migration

- [ ] Run: `cd backend && alembic upgrade head` (ensure it applies cleanly against the dev DB)
- [ ] Run: `cd backend && alembic downgrade -1 && alembic upgrade head` (verify round-trip)

---

## Task 2: Background metrics collector (`app/core/monitoring/`)

**Files:**
- Create: `backend/app/core/monitoring/__init__.py`
- Create: `backend/app/core/monitoring/metrics_collector.py`
- Create: `backend/tests/test_metrics_collector.py`
- Modify: `backend/app/api/app.py` (start collector in `_lifespan`)

**Interfaces:**
- Consumes: `ContainerOrchestrator.get_stats()`, `get_session_factory()`, `ContainerMetric` ORM model
- Produces: `run_metrics_collector()` — async loop, started as `asyncio.Task`

### 2.1 Create `app/core/monitoring/__init__.py`

- [ ] Create empty `backend/app/core/monitoring/__init__.py`:

```python
"""Metrics collection — time-series storage for container resource usage."""
```

### 2.2 Write `metrics_collector.py`

- [ ] Create `backend/app/core/monitoring/metrics_collector.py`:

```python
"""Background worker that polls Docker stats and persists to Postgres."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import ProviderConnectionError
from app.db.models import ContainerMetric

logger = logging.getLogger(__name__)

METRICS_INTERVAL_SECONDS = int(
    os.environ.get("VELA_METRICS_INTERVAL_SECONDS", "30").strip()
)
METRICS_RETENTION_DAYS = int(
    os.environ.get("VELA_METRICS_RETENTION_DAYS", "30").strip()
)


async def collect_and_store_once(
    orchestrator: ContainerOrchestrator, session: AsyncSession,
) -> None:
    """Poll stats for all Vela-managed containers and persist one row each."""
    try:
        containers = await orchestrator.list()
    except ProviderConnectionError:
        logger.debug("Docker unavailable; skipping metrics collection pass")
        return

    vela_containers = [
        c for c in containers if "vela.managed" in (c.labels or {})
    ]

    rows: list[ContainerMetric] = []
    for container in vela_containers:
        try:
            stats = await orchestrator.get_stats(container.id)
        except ProviderConnectionError:
            logger.debug(
                "Docker unavailable for %s; skipping", container.id
            )
            continue
        except Exception:
            logger.exception(
                "Failed to collect stats for container %s", container.id
            )
            continue

        rows.append(
            ContainerMetric(
                container_id=stats.container_id,
                timestamp=stats.timestamp,
                cpu_percent=stats.cpu_percent,
                memory_usage_bytes=stats.memory_usage_bytes,
                memory_limit_bytes=stats.memory_limit_bytes,
                memory_percent=stats.memory_percent,
                network_rx_bytes=stats.network_rx_bytes,
                network_tx_bytes=stats.network_tx_bytes,
            )
        )

    if rows:
        session.add_all(rows)
        await session.commit()
        logger.debug("Stored %d metric rows", len(rows))


async def cleanup_expired_metrics(session: AsyncSession) -> None:
    """Delete metric rows older than METRICS_RETENTION_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=METRICS_RETENTION_DAYS)
    result = await session.execute(
        delete(ContainerMetric).where(ContainerMetric.timestamp < cutoff)
    )
    await session.commit()
    if result.rowcount:
        logger.info("Cleaned up %d expired metric rows", result.rowcount)


async def run_metrics_collector() -> None:
    """Continuous collection loop for the lifetime of the application."""
    from app.api.deps import get_orchestrator
    from app.db.engine import get_session_factory

    logger.info(
        "Starting metrics collector (interval=%ds, retention=%dd)",
        METRICS_INTERVAL_SECONDS,
        METRICS_RETENTION_DAYS,
    )

    session_factory = get_session_factory()
    cleanup_counter = 0

    while True:
        try:
            orchestrator = get_orchestrator()
            async with session_factory() as session:
                await collect_and_store_once(orchestrator, session)

                # Run cleanup every 10 collection cycles (~5 min at 30s interval)
                cleanup_counter += 1
                if cleanup_counter >= 10:
                    cleanup_counter = 0
                    await cleanup_expired_metrics(session)
        except asyncio.CancelledError:
            logger.info("Metrics collector stopped")
            break
        except ProviderConnectionError:
            logger.debug("Docker unavailable; skipping metrics collection pass")
        except Exception:
            logger.exception("Unexpected error in metrics collector loop")

        await asyncio.sleep(METRICS_INTERVAL_SECONDS)
```

### 2.3 Write test for collector logic

- [ ] Create `backend/tests/test_metrics_collector.py`:

```python
"""Unit tests for metrics collector logic."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.models import ContainerInfo
from app.core.monitoring.metrics_collector import (
    collect_and_store_once,
    cleanup_expired_metrics,
)
from app.db.models import ContainerMetric
from app.core.enums import ContainerStatus, HealthStatus
from app.core.containers.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_MANAGED_VALUE,
    VELA_OWNER_LABEL,
)

os.environ.setdefault("VELA_METRICS_INTERVAL_SECONDS", "1")


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
    db_session_factory, seeded_orchestrator: FakeContainerOrchestrator
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
```

- [ ] Run: `cd backend && python -m pytest tests/test_metrics_collector.py -q` — ensure all 3 tests pass

### 2.4 Wire collector into app lifespan

- [ ] Modify `backend/app/api/app.py` — add import and task in `_lifespan`:

```python
# Add to imports inside _lifespan:
from app.core.monitoring.metrics_collector import run_metrics_collector
```

- [ ] In `_lifespan`, after the `monitor_task` line, add:

```python
metrics_task = asyncio.create_task(run_metrics_collector())
```

- [ ] In the `finally` block, add cleanup:

```python
metrics_task.cancel()
# ... existing cleanup ...
with suppress(asyncio.CancelledError):
    await metrics_task
```

The full `_lifespan` should look like:

```python
@asynccontextmanager
async def _lifespan(_application: FastAPI):
    from app.api.deps import get_orchestrator, get_traffic_router
    from app.core.exceptions import ProviderConnectionError, TrafficRouterError
    from app.core.notifications.container_monitor import run_monitoring_loop
    from app.core.scaling.scaling_engine import run_scaling_loop
    from app.core.monitoring.metrics_collector import run_metrics_collector
    from app.e2e_support import ensure_e2e_database

    await ensure_e2e_database()

    monitor_task = asyncio.create_task(run_monitoring_loop())
    metrics_task = asyncio.create_task(run_metrics_collector())
    scaling_task: asyncio.Task[None] | None = None
    try:
        orchestrator = get_orchestrator()
        traffic_router = get_traffic_router()
    except (ProviderConnectionError, TrafficRouterError) as exc:
        logger.warning(
            "Scaling dependencies unavailable at startup (%s); auto-scaling loop will not run.",
            exc,
        )
    else:
        scaling_task = asyncio.create_task(
            run_scaling_loop(orchestrator, traffic_router)
        )

    try:
        yield
    finally:
        monitor_task.cancel()
        metrics_task.cancel()
        if scaling_task is not None:
            scaling_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
        with suppress(asyncio.CancelledError):
            await metrics_task
        if scaling_task is not None:
            with suppress(asyncio.CancelledError):
                await scaling_task
```

---

## Task 3: API endpoints for metrics

**Files:**
- Create: `backend/app/api/routes/metrics.py`
- Modify: `backend/app/api/schemas.py` (add response schemas)
- Modify: `backend/app/api/routes/__init__.py` (export `metrics`)
- Modify: `backend/app/api/app.py` (mount router)
- Create: `backend/tests/test_metrics_api.py`

**Interfaces:**
- Consumes: `ContainerMetric` ORM, `require_container_access` from containers routes
- Produces: `GET /api/metrics` (raw time-series), `GET /api/metrics/summary` (aggregated)

### 3.1 Add API schemas

- [ ] Append to `backend/app/api/schemas.py`:

```python
# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class MetricPoint(BaseModel):
    """Single stored metric row returned to the client."""

    timestamp: datetime
    cpu_percent: float
    memory_usage_bytes: int
    memory_limit_bytes: int
    memory_percent: float
    network_rx_bytes: int
    network_tx_bytes: int


class MetricSummary(BaseModel):
    """Aggregated stats for a time bucket."""

    bucket_start: datetime
    cpu_avg: float
    cpu_max: float
    cpu_min: float
    memory_usage_avg: int
    memory_usage_max: int
    memory_limit_avg: int
    memory_percent_avg: float
    memory_percent_max: float
    network_rx_total: int
    network_tx_total: int
```

### 3.2 Create metrics route module

- [ ] Create `backend/app/api/routes/metrics.py`:

```python
"""Metrics time-series API."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import MetricPoint, MetricSummary
from app.core.containers.docker_orchestrator import VELA_OWNER_LABEL
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.db.access_control import require_container_access
from app.db.models import ContainerMetric, User
from app.api.deps import get_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def get_metrics(
    container_id: str,
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> list[MetricPoint]:
    """Return recent metric points for a container."""
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )

    since = func.now() - timedelta(hours=hours)
    stmt = (
        select(ContainerMetric)
        .where(
            ContainerMetric.container_id == container_id,
            ContainerMetric.timestamp >= since,
        )
        .order_by(ContainerMetric.timestamp.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [
        MetricPoint(
            timestamp=row.timestamp,
            cpu_percent=row.cpu_percent,
            memory_usage_bytes=row.memory_usage_bytes,
            memory_limit_bytes=row.memory_limit_bytes,
            memory_percent=row.memory_percent,
            network_rx_bytes=row.network_rx_bytes,
            network_tx_bytes=row.network_tx_bytes,
        )
        for row in rows
    ]


@router.get("/summary")
async def get_metrics_summary(
    container_id: str,
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> list[MetricSummary]:
    """Return aggregated metric summaries grouped by 1-hour buckets."""
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )

    since = func.now() - timedelta(hours=hours)
    stmt = (
        select(
            func.date_trunc("hour", ContainerMetric.timestamp).label("bucket_start"),
            func.avg(ContainerMetric.cpu_percent).label("cpu_avg"),
            func.max(ContainerMetric.cpu_percent).label("cpu_max"),
            func.min(ContainerMetric.cpu_percent).label("cpu_min"),
            func.avg(ContainerMetric.memory_usage_bytes).label("memory_usage_avg"),
            func.max(ContainerMetric.memory_usage_bytes).label("memory_usage_max"),
            func.avg(ContainerMetric.memory_limit_bytes).label("memory_limit_avg"),
            func.avg(ContainerMetric.memory_percent).label("memory_percent_avg"),
            func.max(ContainerMetric.memory_percent).label("memory_percent_max"),
            func.sum(ContainerMetric.network_rx_bytes).label("network_rx_total"),
            func.sum(ContainerMetric.network_tx_bytes).label("network_tx_total"),
        )
        .where(
            ContainerMetric.container_id == container_id,
            ContainerMetric.timestamp >= since,
        )
        .group_by(func.date_trunc("hour", ContainerMetric.timestamp))
        .order_by(func.date_trunc("hour", ContainerMetric.timestamp).asc())
    )
    result = await session.execute(stmt)
    rows = result.mappings().all()

    return [
        MetricSummary(
            bucket_start=row["bucket_start"],
            cpu_avg=round(float(row["cpu_avg"]), 2) if row["cpu_avg"] else 0.0,
            cpu_max=round(float(row["cpu_max"]), 2) if row["cpu_max"] else 0.0,
            cpu_min=round(float(row["cpu_min"]), 2) if row["cpu_min"] else 0.0,
            memory_usage_avg=int(row["memory_usage_avg"]) if row["memory_usage_avg"] else 0,
            memory_usage_max=int(row["memory_usage_max"]) if row["memory_usage_max"] else 0,
            memory_limit_avg=int(row["memory_limit_avg"]) if row["memory_limit_avg"] else 0,
            memory_percent_avg=round(float(row["memory_percent_avg"]), 2) if row["memory_percent_avg"] else 0.0,
            memory_percent_max=round(float(row["memory_percent_max"]), 2) if row["memory_percent_max"] else 0.0,
            network_rx_total=int(row["network_rx_total"]) if row["network_rx_total"] else 0,
            network_tx_total=int(row["network_tx_total"]) if row["network_tx_total"] else 0,
        )
        for row in rows
    ]
```

- [ ] Note: The import `require_container_access` lives in `backend/app/api/routes/containers.py`. To avoid circular imports, import it inline inside each handler, or extract it to `app/core/db/access_control.py`. Since the containers route already imports it, check if it's defined in containers.py or a separate module. If it's in containers.py, use:

```python
from app.api.routes.containers import require_container_access
```

If `require_container_access` is not importable from another module, add the import at the top of `metrics.py`:

```python
from app.api.routes.containers import require_container_access
```

### 3.3 Register metrics router

- [ ] Add `metrics` to `backend/app/api/routes/__init__.py`:

```python
from app.api.routes import (
    auth,
    builder,
    containers,
    deployments,
    dockerfile_templates,
    github,
    images,
    metrics,  # <-- add
    projects,
    scaling,
    settings,
    stacks,
    traffic,
    users,
)
```

- [ ] In `backend/app/api/app.py`, add the router mount (after the stacks router):

```python
application.include_router(
    metrics.router,
    prefix=f"{API_PREFIX}/metrics",
    tags=["metrics"],
)
```

### 3.4 Write API integration tests

- [ ] Create `backend/tests/test_metrics_api.py`:

```python
"""Integration tests for metrics API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.models import ContainerInfo
from app.db.models import ContainerMetric
from app.core.enums import ContainerStatus, HealthStatus
from app.core.containers.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_MANAGED_VALUE,
    VELA_OWNER_LABEL,
)


@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def metrics_orchestrator(test_user_id: uuid.UUID) -> FakeContainerOrchestrator:
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


def _seed_metrics(
    db_session_factory, container_id: str, count: int = 10
) -> None:
    import asyncio

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

    import asyncio as aio
    aio.run(_run())


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
```

- [ ] Run: `cd backend && python -m pytest tests/test_metrics_api.py -q` — ensure all 5 tests pass

---

## Task 4: Frontend — recharts dependency

**Files:**
- Modify: `frontend/package.json`

### 4.1 Add recharts

- [ ] Run: `cd frontend && npm install --save-exact recharts@2.15.1`
- [ ] Verify `frontend/package.json` has `"recharts": "2.15.1"` (no `^` or `~`)

---

## Task 5: Frontend — metrics API client

**Files:**
- Modify: `frontend/src/api/client.ts`

### 5.1 Add metrics types and functions

- [ ] Append to `frontend/src/api/client.ts` (before the closing of the file, after the stacks section):

```typescript
// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

export interface MetricPoint {
  timestamp: string
  cpu_percent: number
  memory_usage_bytes: number
  memory_limit_bytes: number
  memory_percent: number
  network_rx_bytes: number
  network_tx_bytes: number
}

export interface MetricSummary {
  bucket_start: string
  cpu_avg: number
  cpu_max: number
  cpu_min: number
  memory_usage_avg: number
  memory_usage_max: number
  memory_limit_avg: number
  memory_percent_avg: number
  memory_percent_max: number
  network_rx_total: number
  network_tx_total: number
}

export async function getMetricPoints(
  containerId: string,
  options: { hours?: number; limit?: number } = {}
): Promise<MetricPoint[]> {
  const params = new URLSearchParams({ container_id: containerId })
  if (options.hours != null) params.set('hours', String(options.hours))
  if (options.limit != null) params.set('limit', String(options.limit))
  return apiGet<MetricPoint[]>(`/api/metrics?${params.toString()}`)
}

export async function getMetricSummary(
  containerId: string,
  hours: number = 24
): Promise<MetricSummary[]> {
  const params = new URLSearchParams({
    container_id: containerId,
    hours: String(hours),
  })
  return apiGet<MetricSummary[]>(`/api/metrics/summary?${params.toString()}`)
}
```

---

## Task 6: Frontend — Resource dashboard page

**Files:**
- Create: `frontend/src/pages/ResourceDashboardPage.tsx`
- Create: `frontend/src/components/charts/MetricChart.tsx`
- Modify: `frontend/src/App.tsx` (add route)
- Modify: `frontend/src/components/Navbar.tsx` (add nav link)

### 6.1 Create MetricChart component

- [ ] Create `frontend/src/components/charts/MetricChart.tsx`:

```typescript
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'

type MetricChartProps = {
  data: Record<string, unknown>[]
  dataKey: string
  label: string
  color: string
  yAxisLabel: string
  chartType?: 'line' | 'area'
  referenceLine?: { value: number; label: string }
  formatValue?: (value: number) => string
}

export function MetricChart({
  data,
  dataKey,
  label,
  color,
  yAxisLabel,
  chartType = 'line',
  referenceLine,
  formatValue,
}: MetricChartProps) {
  const formatXAxis = (value: string) => {
    try {
      const d = new Date(value)
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch {
      return String(value)
    }
  }

  const formatTooltipValue = (value: number) =>
    formatValue ? formatValue(value) : value.toFixed(1)

  const ChartComponent = chartType === 'area' ? AreaChart : LineChart

  return (
    <ResponsiveContainer width="100%" height={240}>
      <ChartComponent data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis
          dataKey="timestamp"
          tickFormatter={formatXAxis}
          tick={{ fontSize: 12 }}
        />
        <YAxis
          label={{ value: yAxisLabel, angle: -90, position: 'insideLeft', fontSize: 12 }}
          tick={{ fontSize: 12 }}
          tickFormatter={formatValue}
        />
        <Tooltip
          labelFormatter={(label: string) => new Date(label).toLocaleString()}
          formatter={(value: number) => [formatTooltipValue(value), label]}
        />
        {chartType === 'line' ? (
          <Line
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={2}
            dot={false}
            name={label}
          />
        ) : (
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            fill={color}
            fillOpacity={0.15}
            name={label}
          />
        )}
        {referenceLine && (
          <ReferenceLine
            y={referenceLine.value}
            stroke="#ef4444"
            strokeDasharray="4 4"
            label={{ position: 'right', value: referenceLine.label, fontSize: 11 }}
          />
        )}
      </ChartComponent>
    </ResponsiveContainer>
  )
}
```

### 6.2 Create ResourceDashboardPage

- [ ] Create `frontend/src/pages/ResourceDashboardPage.tsx`:

```typescript
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  formatApiError,
  getMetricPoints,
  listContainers,
  type ContainerInfo,
  type MetricPoint,
} from '../api/client'
import { MetricChart } from '../components/charts/MetricChart'
import { formatBytes } from '../utils/formatBytes'
import { Skeleton } from '../components/Skeleton'

type TimeRange = '1h' | '6h' | '24h' | '7d'

const TIME_RANGE_HOURS: Record<TimeRange, number> = {
  '1h': 1,
  '6h': 6,
  '24h': 24,
  '7d': 168,
}

export default function ResourceDashboardPage() {
  const { containerId } = useParams<{ containerId: string }>()
  const [timeRange, setTimeRange] = useState<TimeRange>('24h')
  const [metrics, setMetrics] = useState<MetricPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [containerName, setContainerName] = useState<string>('')

  const hours = TIME_RANGE_HOURS[timeRange]

  const fetchMetrics = useCallback(async () => {
    if (!containerId) return
    setLoading(true)
    setError(null)
    try {
      const points = await getMetricPoints(containerId, { hours })
      setMetrics(points.reverse())
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setLoading(false)
    }
  }, [containerId, hours])

  useEffect(() => {
    void fetchMetrics()
  }, [fetchMetrics])

  useEffect(() => {
    const loadName = async () => {
      try {
        const containers = await listContainers()
        const matched = containers.find((c) => c.id === containerId)
        if (matched) setContainerName(matched.name)
      } catch {
        // non-critical
      }
    }
    if (containerId) void loadName()
  }, [containerId])

  const chartData = useMemo(() => {
    return metrics.map((m) => ({
      timestamp: m.timestamp,
      cpu: m.cpu_percent,
      memoryUsage: m.memory_usage_bytes,
      memoryLimit: m.memory_limit_bytes,
      memoryPercent: m.memory_percent,
      networkRx: m.network_rx_bytes,
      networkTx: m.network_tx_bytes,
    }))
  }, [metrics])

  const timeRangeButtons: TimeRange[] = ['1h', '6h', '24h', '7d']

  return (
    <section className="dashboard-page">
      <h1 className="dashboard-page__title">
        Resource Dashboard
        {containerName ? ` — ${containerName}` : ''}
      </h1>

      <div className="metrics-toolbar" style={{ display: 'flex', gap: '8px', marginBottom: '16px', alignItems: 'center' }}>
        <span style={{ fontSize: '14px', color: '#6b7280' }}>Time range:</span>
        {timeRangeButtons.map((range) => (
          <button
            key={range}
            type="button"
            className={`btn btn--sm ${timeRange === range ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => setTimeRange(range)}
          >
            {range}
          </button>
        ))}
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => void fetchMetrics()}
          disabled={loading}
          style={{ marginLeft: 'auto' }}
        >
          Refresh
        </button>
      </div>

      {error ? (
        <div className="containers-banner containers-banner--err" role="alert">
          <p className="containers-banner__text">{error}</p>
        </div>
      ) : null}

      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} height={240} />
          ))}
        </div>
      ) : metrics.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', color: '#6b7280' }}>
          <p>No metrics data available yet.</p>
          <p style={{ fontSize: '14px' }}>
            The background collector records stats every 30 seconds. Data will appear here shortly.
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div className="metrics-card" style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#374151' }}>CPU Usage</h3>
            <MetricChart
              data={chartData}
              dataKey="cpu"
              label="CPU %"
              color="#3b82f6"
              yAxisLabel="CPU %"
              formatValue={(v) => `${v.toFixed(1)}%`}
            />
          </div>

          <div className="metrics-card" style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#374151' }}>Memory Usage</h3>
            <MetricChart
              data={chartData}
              dataKey="memoryUsage"
              label="Memory"
              color="#10b981"
              yAxisLabel="Memory"
              chartType="area"
              formatValue={formatBytes}
              referenceLine={
                chartData.length > 0
                  ? { value: chartData[0].memoryLimit, label: 'Limit' }
                  : undefined
              }
            />
          </div>

          <div className="metrics-card" style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#374151' }}>Memory Percent</h3>
            <MetricChart
              data={chartData}
              dataKey="memoryPercent"
              label="Memory %"
              color="#f59e0b"
              yAxisLabel="Mem %"
              chartType="area"
              formatValue={(v) => `${v.toFixed(1)}%`}
            />
          </div>

          <div className="metrics-card" style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#374151' }}>Network I/O</h3>
            <MetricChart
              data={chartData}
              dataKey="networkRx"
              label="Network Rx"
              color="#8b5cf6"
              yAxisLabel="Bytes"
              formatValue={formatBytes}
            />
          </div>
        </div>
      )}
    </section>
  )
}
```

### 6.3 Add route to App.tsx

- [ ] Add import in `frontend/src/App.tsx`:

```typescript
import ResourceDashboardPage from './pages/ResourceDashboardPage'
```

- [ ] Add route after the `/dashboard` route:

```typescript
<Route
  path="/containers/:containerId/resources"
  element={
    <RequireAuth>
      <ResourceDashboardPage />
    </RequireAuth>
  }
/>
```

### 6.4 Add nav link in Navbar

- [ ] Read `frontend/src/components/Navbar.tsx` to find the nav links section
- [ ] Add a "Resources" link that navigates to `/containers/${containerId}/resources`. The link should appear in the container detail context. For now, add it as a link from the DashboardPage — each workload row can have a "Resources" button.

### 6.5 Add "Resources" button to WorkloadsTable

- [ ] Read `frontend/src/components/workloads/WorkloadsTable.tsx` to find the action buttons section
- [ ] Add a `onViewResources` prop to the `WorkloadsTable` component interface
- [ ] Add a button in each row that calls `onViewResources(container.id)`
- [ ] In `DashboardPage.tsx`, wire the handler:

```typescript
import { useNavigate } from 'react-router-dom'

// Inside DashboardPage:
const navigate = useNavigate()

const onViewResources = useCallback((containerId: string) => {
  navigate(`/containers/${containerId}/resources`)
}, [navigate])
```

- [ ] Pass `onViewResources={onViewResources}` to `<WorkloadsTable>`

---

## Task 7: Verification

### 7.1 Backend tests

- [ ] Run: `cd backend && python -m pytest tests -q` — all existing tests + new tests pass

### 7.2 Frontend build

- [ ] Run: `cd frontend && npm run build` — clean build with no TypeScript errors

### 7.3 Manual smoke test

- [ ] Start backend: `cd backend && python run.py`
- [ ] Start frontend: `cd frontend && npm run dev`
- [ ] Deploy a container, wait 60+ seconds, navigate to the container's resource dashboard
- [ ] Verify charts render with data points
- [ ] Verify time range selector switches data correctly

---

## Self-Review Checklist

- [ ] **Spec coverage**: DB model (Task 1), migration (Task 1), background collector (Task 2), API raw points (Task 3), API summary (Task 3), frontend charts (Task 6), time range selector (Task 6), recharts (Task 4)
- [ ] **Placeholder scan**: No "TBD", "TODO", "add validation", or "write tests" strings remain — every step has concrete code
- [ ] **Type consistency**: `ContainerMetric` ORM uses `Float`/`Integer` matching `ContainerStats` pydantic model; frontend `MetricPoint`/`MetricSummary` types match API schemas
- [ ] **Naming**: `VELA_METRICS_INTERVAL_SECONDS`, `VELA_METRICS_RETENTION_DAYS` follow existing `VELA_*` convention
- [ ] **MVC compliance**: Domain logic in `app/core/monitoring/`, schemas in `app/api/schemas.py`, routes in `app/api/routes/metrics.py`
- [ ] **Index on (container_id, timestamp desc)**: Composite index `ix_container_metrics_container_timestamp` created in migration and ORM model
- [ ] **Cleanup cron**: Runs every 10 collection cycles in `run_metrics_collector()`, deletes rows older than `METRICS_RETENTION_DAYS`
- [ ] **Exact npm versions**: `recharts@2.15.1` with `--save-exact`, no `^` or `~`
