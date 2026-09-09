# Resource Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Time-series charts of CPU, memory, and network usage per container, plus per-user/team usage totals. Background collector polls Docker stats and stores in Postgres.

**Architecture:** Background worker polls container stats at 30s intervals, stores in `container_metrics` table. API provides raw points, hourly summaries, and a per-user/team usage rollup. Frontend renders charts with recharts and a dashboard usage section.

**Tech Stack:** SQLAlchemy 2.x, Alembic, PostgreSQL (SQLite in tests), FastAPI, React, recharts, TypeScript

## Corrections (2026-08-16 review)

1. **Migration:** `0015_stack_service_git_branch` already exists and head is `0016_build_override`. The new migration is `0017_container_metrics` with `down_revision = "0016_build_override"`.
2. **SQLite:** tests run on in-memory SQLite. `func.date_trunc()` is Postgres-only and `func.now() - timedelta` is unreliable there → `since` is computed in Python and summary buckets are built in Python (window ≤ 168 h ≈ 20k rows at 30 s).
3. **Column widths:** byte counters overflow 32-bit `Integer` at 2 GiB → `BigInteger` for the four byte columns.
4. **Index:** the standalone `container_id` index is redundant with the composite `(container_id, timestamp)` index.
5. **Imports:** `require_container_access` lives in `app.core.projects.access` (not `app.core.db.access_control`; `routes/containers.py` only re-imports it).
6. **Collector DI:** `run_metrics_collector(orchestrator)` takes the orchestrator as a parameter (scaling-loop pattern) instead of calling `get_orchestrator()` inside the loop.
7. **Tests:** drop the dead `metrics_orchestrator`/`test_user_id` fixtures in `test_metrics_api.py` — `api_client`'s shared fake already seeds `cid-1` owned by the seeded user, which is what the tests query.
8. **Skeleton:** the component takes `className` only, not `height` — wrap skeleton placeholders in a fixed-height div.
9. **Navigation:** no global "Resources" navbar item (the page is per-container) — the entry point is a "Resources" button in each `WorkloadsTable` row.
10. **User/team rollup (new: `get_usage` route in Task 3 + panel in Task 6.6):** `GET /api/metrics/usage` groups the caller's accessible containers by project/team with totals, backed by each container's latest stored metric. Hard quota enforcement at deploy time remains out of scope (product decision pending).

## Status (2026-09-02)

- All tasks implemented.
- Alembic head is now `0019_merge_resource_management` (0017 is in the chain, no longer orphaned at head `0016`).
- Task 3.3's `routes/__init__.py` export step was not done (file is docstring-only, `app.py` imports the submodule directly).
- The metrics client lives in `frontend/src/api/metrics.ts` (re-exported from `client.ts`).
- `GET /api/metrics/usage` additionally returns team storage quota fields (see `2026-08-16-team-storage-quota.md`).
- The Task 6 inline-hex UI snippets were superseded by design-token CSS (see `2026-09-02-resource-management-premerge-fixes.md` Task 3).

## Global Constraints

- Python 3.12+, TypeScript, exact npm versions (no ^ or ~)
- Backend MVC: core/ (domain), schemas.py (views), routes/ (controllers)
- Domain packages under `app/core/<domain>/` when 3+ modules (small 2-file packages exist already — `security/` — so `monitoring/` with one module follows that precedent)
- TDD: write failing test first, then minimal implementation
- Metrics collector runs as background asyncio.Task (like container_monitor)
- Configurable retention to prevent unbounded growth
- Use `recharts` for frontend charts (add to package.json)

---

## Task 1: Add `ContainerMetric` ORM model and Alembic migration

**Files:**
- Create: `backend/app/db/models.py` (append `ContainerMetric` class)
- Create: `backend/alembic/versions/0017_container_metrics.py`

No conftest change is needed for this task — the test engine already runs
`Base.metadata.create_all`, which picks up the new model automatically.

**Interfaces:**
- Produces: `ContainerMetric` ORM model on `Base.metadata`

### 1.1 Add `ContainerMetric` ORM model

- [x] Append the following class to `backend/app/db/models.py` (after `StackComposition`, before EOF):

(`BigInteger` for the byte counters — 32-bit `Integer` overflows at 2 GiB.
Composite index alone; a standalone `container_id` index is redundant with its prefix.)

```python
class ContainerMetric(Base):
    __tablename__ = "container_metrics"
    __table_args__ = (
        sa.Index("ix_container_metrics_container_timestamp", "container_id", "timestamp", postgresql_using="btree"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    container_id: Mapped[str] = mapped_column(String(128), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    cpu_percent: Mapped[float] = mapped_column(Float, nullable=False)
    memory_usage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memory_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memory_percent: Mapped[float] = mapped_column(Float, nullable=False)
    network_rx_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    network_tx_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
```

- [x] Extend the existing `from sqlalchemy import (...)` in `backend/app/db/models.py` with `BigInteger` and make the aliased `import sqlalchemy as sa` present (needed for `sa.Index`); `_utcnow`, `Uuid`, `String`, `DateTime`, `Float` are already imported there.

### 1.2 Create Alembic migration

- [x] Write `backend/alembic/versions/0017_container_metrics.py` (head is `0016_build_override`; `0015` is taken by `0015_stack_service_git_branch`):

```python
"""Add container_metrics table for time-series resource data.

Revision ID: 0017_container_metrics
Revises: 0016_build_override
Create Date: 2026-08-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_container_metrics"
down_revision: str | Sequence[str] | None = "0016_build_override"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "container_metrics",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_usage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_percent", sa.Float(), nullable=False),
        sa.Column("network_rx_bytes", sa.BigInteger(), nullable=False),
        sa.Column("network_tx_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
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
    op.drop_table("container_metrics")
```

### 1.3 Verify migration

- [x] Run: `cd backend && alembic upgrade head` (ensure it applies cleanly against the dev DB)
- [x] Run: `cd backend && alembic downgrade -1 && alembic upgrade head` (verify round-trip)

---

## Task 2: Background metrics collector (`app/core/monitoring/`)

**Files:**
- Create: `backend/app/core/monitoring/__init__.py`
- Create: `backend/app/core/monitoring/metrics_collector.py`
- Create: `backend/tests/test_metrics_collector.py`
- Modify: `backend/app/api/app.py` (start collector in `_lifespan`)
- Modify: `backend/tests/conftest.py` (force collector interval, Step 2.4)

**Interfaces:**
- Consumes: `ContainerOrchestrator.get_stats()`, `get_session_factory()`, `ContainerMetric` ORM model
- Produces: `run_metrics_collector(orchestrator)` — async loop started as `asyncio.Task` (takes the orchestrator as a parameter, same pattern as `run_scaling_loop`, so test DI overrides apply)

### 2.1 Create `app/core/monitoring/__init__.py`

- [x] Create empty `backend/app/core/monitoring/__init__.py`:

```python
"""Metrics collection — time-series storage for container resource usage."""
```

### 2.2 Write `metrics_collector.py`

- [x] Create `backend/app/core/monitoring/metrics_collector.py`:

```python
"""Background worker that polls Docker stats and persists to Postgres."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.docker_orchestrator import VELA_MANAGED_LABEL
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
        c for c in containers if VELA_MANAGED_LABEL in (c.labels or {})
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


Append this to the **same file** (`metrics_collector.py`):

`run_metrics_collector` takes the orchestrator as a parameter (resolved once in the
lifespan, like `run_scaling_loop`) so DI overrides in tests apply and the loop
does not re-resolve dependencies every cycle. `collect_and_store_once` already
swallows `ProviderConnectionError`, so the loop only needs the generic catch:

```python
async def run_metrics_collector(orchestrator: ContainerOrchestrator) -> None:
    """Continuous collection loop for the lifetime of the application."""
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
        except Exception:
            logger.exception("Unexpected error in metrics collector loop")

        await asyncio.sleep(METRICS_INTERVAL_SECONDS)
```

### 2.3 Write test for collector logic

- [x] Create `backend/tests/test_metrics_collector.py`:

(The module-level env constants in `metrics_collector` are read at import time;
these tests exercise `collect_and_store_once`/`cleanup_expired_metrics` directly
and never touch the interval, so no env setup is needed. `pyproject.toml` sets
`asyncio_mode = "auto"`, so the bare `async def` tests run as-is.)

```python
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

- [x] Run: `cd backend && python -m pytest tests/test_metrics_collector.py -q` — ensure all 3 tests pass

### 2.4 Wire collector into app lifespan

- [x] Modify `backend/app/api/app.py` `_lifespan` as below. The metrics task must be created **after** `get_orchestrator()` succeeds (it needs the instance as an argument), and skipped when the provider is unavailable — exactly like the scaling task:

```python
@asynccontextmanager
async def _lifespan(_application: FastAPI):
    from app.api.deps import get_orchestrator, get_traffic_router
    from app.core.exceptions import ProviderConnectionError, TrafficRouterError
    from app.core.notifications.container_monitor import run_monitoring_loop
    from app.core.monitoring.metrics_collector import run_metrics_collector
    from app.core.scaling.scaling_engine import run_scaling_loop
    from app.e2e_support import ensure_e2e_database

    await ensure_e2e_database()

    monitor_task = asyncio.create_task(run_monitoring_loop())
    metrics_task: asyncio.Task[None] | None = None
    scaling_task: asyncio.Task[None] | None = None
    try:
        orchestrator = get_orchestrator()
        traffic_router = get_traffic_router()
    except (ProviderConnectionError, TrafficRouterError) as exc:
        logger.warning(
            "Container provider unavailable at startup (%s); metrics and scaling loops will not run.",
            exc,
        )
    else:
        metrics_task = asyncio.create_task(run_metrics_collector(orchestrator))
        scaling_task = asyncio.create_task(
            run_scaling_loop(orchestrator, traffic_router)
        )

    try:
        yield
    finally:
        monitor_task.cancel()
        if metrics_task is not None:
            metrics_task.cancel()
        if scaling_task is not None:
            scaling_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
        if metrics_task is not None:
            with suppress(asyncio.CancelledError):
                await metrics_task
        if scaling_task is not None:
            with suppress(asyncio.CancelledError):
                await scaling_task
```

- [x] In `backend/tests/conftest.py`, force the interval like the existing monitor
  constant (a developer `.env` must not change module-level collector constants
  in tests):

```python
os.environ["VELA_METRICS_INTERVAL_SECONDS"] = "3600"
```

Known test behavior (accepted, same as the monitor/scaling loops): the
lifespan starts the collector in every `TestClient`, and the first collection
pass hits the env-var `:memory:` engine which has no schema, logging one
exception line. Subsequent cycles are suppressed by the forced interval.

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

- [x] Append to `backend/app/api/schemas.py` (`uuid` and `datetime` are already imported there):

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


class ContainerUsageEntry(BaseModel):
    """One container's latest stored usage snapshot (None usage = not running)."""

    container_id: str
    name: str
    status: str
    project_id: uuid.UUID | None
    project_name: str | None
    team_name: str | None
    cpu_percent: float | None
    memory_usage_bytes: int | None
    memory_percent: float | None


class ProjectUsage(BaseModel):
    """Latest usage across one project's containers (team or personal)."""

    project_id: uuid.UUID | None
    project_name: str | None
    team_name: str | None
    cpu_percent_total: float
    memory_usage_bytes_total: int
    containers: list[ContainerUsageEntry]


class UsageSummary(BaseModel):
    """Latest resource usage for every container the caller can access."""

    projects: list[ProjectUsage]
    total_cpu_percent: float
    total_memory_usage_bytes: int
    running_containers: int
```

### 3.2 Create metrics route module

- [x] Create `backend/app/api/routes/metrics.py`:

`since` is computed in Python and summary buckets are built in Python: the test
suite runs on in-memory SQLite, where `date_trunc()` does not exist and
`now() - timedelta` is dialect-unreliable. A 168 h window at 30 s resolution is
~20k rows — trivial to aggregate in-process.

```python
"""Metrics time-series API."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_orchestrator
from app.api.schemas import (
    ContainerUsageEntry,
    MetricPoint,
    MetricSummary,
    ProjectUsage,
    UsageSummary,
)
from app.core.containers.docker_orchestrator import (
    VELA_PROJECT_LABEL,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.enums import ContainerStatus
from app.core.projects.access import (
    list_accessible_project_ids,
    require_container_access,
)
from app.core.models import ContainerInfo
from app.db.models import (
    ContainerMetric,
    Organization,
    Project,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _metric_point(row: ContainerMetric) -> MetricPoint:
    return MetricPoint(
        timestamp=row.timestamp,
        cpu_percent=row.cpu_percent,
        memory_usage_bytes=row.memory_usage_bytes,
        memory_limit_bytes=row.memory_limit_bytes,
        memory_percent=row.memory_percent,
        network_rx_bytes=row.network_rx_bytes,
        network_tx_bytes=row.network_tx_bytes,
    )


def _aware(ts: datetime) -> datetime:
    # SQLite reads back naive UTC; Postgres returns aware datetimes.
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


async def _rows_since(
    session: AsyncSession, container_id: str, hours: int
) -> list[ContainerMetric]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(ContainerMetric)
        .where(
            ContainerMetric.container_id == container_id,
            ContainerMetric.timestamp >= since,
        )
        .order_by(ContainerMetric.timestamp.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("")
async def get_metrics(
    container_id: str,
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> list[MetricPoint]:
    """Return the newest stored metric points for a container, in time order."""
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )
    rows = await _rows_since(session, container_id, hours)
    newest_first = list(reversed(rows))[:limit]
    return [_metric_point(row) for row in reversed(newest_first)]


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
    rows = await _rows_since(session, container_id, hours)

    buckets: dict[datetime, list[ContainerMetric]] = {}
    for row in rows:
        bucket_start = _aware(row.timestamp).replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(bucket_start, []).append(row)

    return [
        MetricSummary(
            bucket_start=bucket_start,
            cpu_avg=round(sum(r.cpu_percent for r in bucket) / len(bucket), 2),
            cpu_max=round(max(r.cpu_percent for r in bucket), 2),
            cpu_min=round(min(r.cpu_percent for r in bucket), 2),
            memory_usage_avg=int(sum(r.memory_usage_bytes for r in bucket) / len(bucket)),
            memory_usage_max=max(r.memory_usage_bytes for r in bucket),
            memory_limit_avg=int(sum(r.memory_limit_bytes for r in bucket) / len(bucket)),
            memory_percent_avg=round(sum(r.memory_percent for r in bucket) / len(bucket), 2),
            memory_percent_max=round(max(r.memory_percent for r in bucket), 2),
            network_rx_total=sum(r.network_rx_bytes for r in bucket),
            network_tx_total=sum(r.network_tx_bytes for r in bucket),
        )
        for bucket_start, bucket in sorted(buckets.items())
    ]


@router.get("/usage", response_model=UsageSummary)
async def get_usage(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> UsageSummary:
    """Latest resource usage for every container the caller can access.

    Grouped by project (team or personal) so users and team members can see
    what each team's workloads consume. Only running containers report usage;
    their stored rows for stopped containers would be stale.
    """
    project_ids = await list_accessible_project_ids(session, current_user.id)
    containers = await orchestrator.list(
        project_ids=project_ids, user_id=current_user.id
    )
    if not containers:
        return UsageSummary(
            projects=[],
            total_cpu_percent=0.0,
            total_memory_usage_bytes=0,
            running_containers=0,
        )

    latest = await latest_metric_by_container(session, [c.id for c in containers])
    projects = (
        (await session.execute(select(Project).where(Project.id.in_(project_ids))))
        .scalars()
        .all()
    )
    project_by_id = {p.id: p for p in projects}
    orgs = (
        (
            await session.execute(
                select(Organization).where(
                    Organization.id.in_({p.organization_id for p in projects})
                )
            )
        )
        .scalars()
        .all()
    )
    org_by_id = {o.id: o for o in orgs}

    grouped: dict[uuid.UUID | None, list[ContainerInfo]] = {}
    for info in containers:
        raw_project_id = info.labels.get(VELA_PROJECT_LABEL)
        try:
            project_id: uuid.UUID | None = (
                uuid.UUID(raw_project_id) if raw_project_id else None
            )
        except ValueError:
            project_id = None
        grouped.setdefault(project_id, []).append(info)

    project_usages: list[ProjectUsage] = []
    total_cpu = 0.0
    total_memory = 0
    running = 0
    for project_id, members in grouped.items():
        project = project_by_id.get(project_id) if project_id else None
        entries: list[ContainerUsageEntry] = []
        for info in members:
            is_running = info.status == ContainerStatus.RUNNING
            row = latest.get(info.id) if is_running else None
            if row is not None:
                total_cpu += row.cpu_percent
                total_memory += row.memory_usage_bytes
            if is_running:
                running += 1
            entries.append(
                ContainerUsageEntry(
                    container_id=info.id,
                    name=info.name,
                    status=info.status.value,
                    project_id=project_id,
                    project_name=project.name if project else None,
                    team_name=(
                        org_by_id[project.organization_id].name
                        if project is not None and project.organization_id in org_by_id
                        else None
                    ),
                    cpu_percent=row.cpu_percent if row else None,
                    memory_usage_bytes=row.memory_usage_bytes if row else None,
                    memory_percent=row.memory_percent if row else None,
                )
            )
        project_usages.append(
            ProjectUsage(
                project_id=project_id,
                project_name=project.name if project else None,
                team_name=(
                    org_by_id[project.organization_id].name
                    if project is not None and project.organization_id in org_by_id
                    else None
                ),
                cpu_percent_total=round(
                    sum(e.cpu_percent or 0.0 for e in entries), 2
                ),
                memory_usage_bytes_total=sum(
                    e.memory_usage_bytes or 0 for e in entries
                ),
                containers=entries,
            )
        )
    project_usages.sort(key=lambda p: p.memory_usage_bytes_total, reverse=True)

    return UsageSummary(
        projects=project_usages,
        total_cpu_percent=round(total_cpu, 2),
        total_memory_usage_bytes=total_memory,
        running_containers=running,
    )


async def latest_metric_by_container(
    session: AsyncSession, container_ids: list[str]
) -> dict[str, ContainerMetric]:
    """Latest stored row per container (empty dict-safe, dialect-safe)."""
    if not container_ids:
        return {}
    subq = (
        select(
            ContainerMetric.container_id,
            func.max(ContainerMetric.timestamp).label("latest_ts"),
        )
        .where(ContainerMetric.container_id.in_(container_ids))
        .group_by(ContainerMetric.container_id)
        .subquery()
    )
    stmt = select(ContainerMetric).join(
        subq,
        (ContainerMetric.container_id == subq.c.container_id)
        & (ContainerMetric.timestamp == subq.c.latest_ts),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {row.container_id: row for row in rows}
```

(import check: `require_container_access` and `list_accessible_project_ids` are
both defined in `app/core/projects/access.py` — `routes/containers.py` only
re-imports them. `/usage` intentionally performs no per-container
`require_container_access` check: the orchestrator list is already filtered by
the caller's memberships.)

### 3.3 Register metrics router

- [x] Add `metrics` to `backend/app/api/routes/__init__.py`:

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

- [x] In `backend/app/api/app.py`, add the router mount (after the stacks router):

```python
application.include_router(
    metrics.router,
    prefix=f"{API_PREFIX}/metrics",
    tags=["metrics"],
)
```

### 3.4 Write API integration tests

Wiring notes: no local fixtures needed — tests use conftest's `api_client`,
`fake_orchestrator` (its app uses that same instance via DI override, and it
already seeds `cid-1` owned by `test_user_id` with no project label),
`anonymous_client`, `db_session_factory`, and `test_user_id`.

- [x] Create `backend/tests/test_metrics_api.py`:

```python
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
```

- [x] Run: `cd backend && python -m pytest tests/test_metrics_api.py -q` — ensure all 8 tests pass

---

## Task 4: Frontend — recharts dependency

**Files:**
- Modify: `frontend/package.json`

### 4.1 Add recharts

- [x] Run: `cd frontend && npm install --save-exact recharts` (installs the
  current stable; do not pin an older hardcoded version)
- [x] Verify `frontend/package.json` has `"recharts": "<exact>"` (no `^` or `~`)
  and `package-lock.json` was updated

---

## Task 5: Frontend — metrics API client

**Files:**
- Modify: `frontend/src/api/client.ts`

### 5.1 Add metrics types and functions

- [x] Append to `frontend/src/api/client.ts` (before the closing of the file, after the stacks section):

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

export interface ContainerUsageEntry {
  container_id: string
  name: string
  status: string
  project_id: string | null
  project_name: string | null
  team_name: string | null
  cpu_percent: number | null
  memory_usage_bytes: number | null
  memory_percent: number | null
}

export interface ProjectUsage {
  project_id: string | null
  project_name: string | null
  team_name: string | null
  cpu_percent_total: number
  memory_usage_bytes_total: number
  containers: ContainerUsageEntry[]
}

export interface UsageSummary {
  projects: ProjectUsage[]
  total_cpu_percent: number
  total_memory_usage_bytes: number
  running_containers: number
}

export async function getUsageSummary(): Promise<UsageSummary> {
  return apiGet<UsageSummary>('/api/metrics/usage')
}
```

---

## Task 6: Frontend — Resource dashboard page

**Files:**
- Create: `frontend/src/pages/ResourceDashboardPage.tsx`
- Create: `frontend/src/components/charts/MetricChart.tsx`
- Create: `frontend/src/pages/containers/ResourceUsagePanel.tsx`
- Modify: `frontend/src/App.tsx` (add route)
- Modify: `frontend/src/pages/DashboardPage.tsx` (usage panel + Resources button wiring)
- Modify: `frontend/src/components/workloads/WorkloadsTable.tsx` (`onViewResources` prop)
- Modify: `frontend/src/index.css` (`.skeleton--metrics-chart`)

### 6.1 Create MetricChart component

- [x] Create `frontend/src/components/charts/MetricChart.tsx`:

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

- [x] Create `frontend/src/pages/ResourceDashboardPage.tsx`:

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

  // Backend returns points in ascending time order — recharts-ready as-is.
  // Container name is loaded in the same request cycle (one effect).
  const fetchMetrics = useCallback(async () => {
    if (!containerId) return
    setLoading(true)
    setError(null)
    try {
      const [points, containers] = await Promise.all([
        getMetricPoints(containerId, { hours }),
        listContainers(),
      ])
      setMetrics(points)
      setContainerName(containers.find((c) => c.id === containerId)?.name ?? '')
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setLoading(false)
    }
  }, [containerId, hours])

  useEffect(() => {
    void fetchMetrics()
  }, [fetchMetrics])

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
            <Skeleton key={i} className="skeleton--metrics-chart" />
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

- [x] Add import in `frontend/src/App.tsx`:

```typescript
import ResourceDashboardPage from './pages/ResourceDashboardPage'
```

- [x] Add route after the `/dashboard` route:

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

### 6.4 Entry points (skip global nav link)

No "Resources" item in `Navbar.tsx`: the app has no container-level context
in the top nav, so a global link would be a no-op. Entry points to the
resource dashboard are the per-row Resources button (6.5) and per-container
rows in the usage section (6.6).

### 6.5 Add "Resources" button to WorkloadsTable

- [x] Read `frontend/src/components/workloads/WorkloadsTable.tsx` to find the action buttons section
- [x] Add a `onViewResources` prop to the `WorkloadsTable` component interface
- [x] Add a button in each row that calls `onViewResources(container.id)`
- [x] In `DashboardPage.tsx`, wire the handler:

```typescript
import { useNavigate } from 'react-router-dom'

// Inside DashboardPage:
const navigate = useNavigate()

const onViewResources = useCallback((containerId: string) => {
  navigate(`/containers/${containerId}/resources`)
}, [navigate])
```

- [x] Pass `onViewResources={onViewResources}` to `<WorkloadsTable>`

### 6.6 Team/user usage rollup panel

The per-container dashboard answers "how much does *this* container use".
The goal is managing resources consumed by **users/teams**, so the dashboard
page also surfaces a per-project (team) rollup of what is running right now.
This is backed by `GET /api/metrics/usage` (Task 3).

- [x] Create `frontend/src/pages/containers/ResourceUsagePanel.tsx` (same folder as
  `DeploymentHistorySection`):

```typescript
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  formatApiError,
  getUsageSummary,
  type UsageSummary,
} from '../../api/client'
import { formatBytes } from '../../utils/formatBytes'
import { Skeleton } from '../Skeleton'

export function ResourceUsagePanel() {
  const navigate = useNavigate()
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getUsageSummary()
      .then((data) => {
        if (!cancelled) setSummary(data)
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    return (
      <section className="dashboard-page__section">
        <p className="containers-banner containers-banner--err">{error}</p>
      </section>
    )
  }

  if (!summary) {
    return (
      <section className="dashboard-page__section" aria-busy="true">
        <Skeleton className="skeleton--detail-title" />
      </section>
    )
  }

  const { projects } = summary
  if (projects.length === 0) {
    return (
      <section className="dashboard-page__section">
        <p style={{ color: '#6b7280', fontSize: 14 }}>
          No running workloads to report usage for.
        </p>
      </section>
    )
  }

  return (
    <section className="dashboard-page__section">
      <h2 className="dashboard-page__subtitle">Resource usage by team</h2>
      <p style={{ color: '#6b7280', fontSize: 14, marginBottom: 12 }}>
        {summary.running_containers} running ·{' '}
        {formatBytes(summary.total_memory_usage_bytes)} memory ·{' '}
        {summary.total_cpu_percent.toFixed(1)}% CPU in total
      </p>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: 12,
        }}
      >
        {projects.map((project, index) => (
          <div
            key={project.project_id ?? `personal-${index}`}
            style={{
              border: '1px solid #e5e7eb',
              borderRadius: 8,
              padding: 16,
            }}
          >
            <h3 style={{ margin: 0, fontSize: 14, color: '#374151' }}>
              {project.team_name ?? project.project_name ?? 'Personal'}
            </h3>
            <p style={{ margin: '4px 0 12px', fontSize: 13, color: '#6b7280' }}>
              {project.memory_usage_bytes_total
                ? formatBytes(project.memory_usage_bytes_total)
                : '0 B'}{' '}
              · {project.cpu_percent_total.toFixed(1)}% CPU
            </p>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {project.containers.map((container) => (
                <li
                  key={container.container_id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: 13,
                    padding: '2px 0',
                  }}
                >
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    style={{ color: '#3b82f6' }}
                    onClick={() =>
                      navigate(
                        `/containers/${container.container_id}/resources`,
                      )
                    }
                  >
                    {container.name}
                  </button>
                  <span style={{ color: '#6b7280' }}>
                    {container.memory_usage_bytes != null
                      ? formatBytes(container.memory_usage_bytes)
                      : 'stopped'}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  )
}
```

- [x] In `DashboardPage.tsx`, import `ResourceUsagePanel` and render it above
  `<DeploymentHistorySection>`:

```typescript
import { ResourceUsagePanel } from './containers/ResourceUsagePanel'

// inside the returned JSX, before <DeploymentHistorySection>:
      <ResourceUsagePanel />
```

### 6.7 CSS

- [x] Add to `frontend/src/index.css` next to the other `.skeleton--*`
  rules (`.skeleton` base sets the shimmer; size variants only set
  width/height):

```css
.skeleton--metrics-chart {
  width: 100%;
  height: 240px;
}
```

---

## Task 7: Verification

### 7.1 Backend tests

- [x] Run: `cd backend && python -m pytest tests -q` — all existing tests + new tests pass

### 7.2 Migration round-trip (needs the dev Postgres from docker compose)

- [x] Run from `backend/`: `alembic upgrade head`
- [x] Run: `alembic downgrade -1`
- [x] Run: `alembic upgrade head`
- [x] Verify the `container_metrics` table exists after the final upgrade

### 7.3 Frontend build and lint

- [x] Run: `cd frontend && npm run build` — clean build with no TypeScript errors
- [x] Run: `cd frontend && npm run lint` — no new findings

### 7.4 E2E suite

- [x] Run: `cd frontend && npm run test:e2e` — the live-SPA E2E suite passes
  (stop any dev server on ports 8000/5173 first; `reuseExistingServer` is off)

### 7.5 Manual smoke test

- [x] Start backend: `cd backend && python run.py`
- [x] Start frontend: `cd frontend && npm run dev`
- [x] Deploy a container, wait 60+ seconds, navigate to the container's resource dashboard
- [x] Verify charts render with data points
- [x] Verify time range selector switches data correctly

---

## Self-Review Checklist

- [x] **Spec coverage**: DB model + migration (Task 1), background collector (Task 2), API raw points / summary / user-team usage rollup (Task 3), frontend charts (Task 6), time range selector (Task 6), team usage panel (Task 6), recharts (Task 4)
- [x] **Placeholder scan**: No "TBD", "TODO", "add validation", or "write tests" strings remain — every step has concrete code
- [x] **Type consistency**: `ContainerMetric` ORM uses `Float`/`BigInteger` (bytes overflow 2 GiB in `Integer`); frontend `MetricPoint`/`MetricSummary`/`UsageSummary` types match API schemas
- [x] **Naming**: `VELA_METRICS_INTERVAL_SECONDS`, `VELA_METRICS_RETENTION_DAYS` follow existing `VELA_*` convention
- [x] **MVC compliance**: Domain logic in `app/core/monitoring/`, schemas in `app/api/schemas.py`, routes in `app/api/routes/metrics.py`
- [x] **Index on (container_id, timestamp)**: Composite `ix_container_metrics_container_timestamp` created in migration and ORM model; no redundant single-column index
- [x] **Cleanup**: Runs every 10 collection cycles in `run_metrics_collector(orchestrator)`, deletes rows older than `METRICS_RETENTION_DAYS`
- [x] **Dialect safety**: No `date_trunc`/`func.now()` — `since` computed and hourly buckets built in Python (test suite runs on SQLite)
- [x] **Exact npm versions**: `recharts` pinned with `--save-exact`, no `^` or `~`
