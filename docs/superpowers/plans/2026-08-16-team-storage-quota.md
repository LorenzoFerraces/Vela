# Team Storage Quota Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-cap each team's total Vela-managed disk (container writable layers + volume uploads) so a deployment can never push a team past its quota, with team-visible usage, an owner-editable quota, and one rising-edge email alert when live usage crosses the limit.

**Architecture:** A new `app/core/quotas/` domain package measures team storage live (Docker inspect `SizeRw` per container, grouped by the `vela.project_id` label, plus per-member upload bytes on disk) and enforces it at the three growth points: `POST /api/containers/run`, `POST /api/containers/deploy` (reject when `used >= quota`; fresh deploys add ~0 writable-layer bytes), and `POST /api/containers/volume-uploads` (reject when `used + upload > quota`). The quota lives on `Project` (each "team" in the UI is a project; personal teams are the bootstrapped personal project) as a nullable override, clamped by the platform default env var (restrict-only). The existing container-monitoring loop re-checks every 20 passes and emails members on the rising edge.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2 async / Alembic / Pytest (in-memory SQLite + `FakeContainerOrchestrator`); React 19 / Vite / Playwright. No new dependencies.

## Global Constraints

- **Execution order:** implement the two resource-management plans first (`2025-08-03-resource-limits.md`, then `2025-08-03-resource-dashboard.md`, which creates migration `0017_container_metrics`). This plan's migration `0018_project_storage_quota` sets `down_revision = "0017_container_metrics"`. **If `0017_container_metrics.py` does not exist in `backend/alembic/versions/` when you start, set `down_revision` to the current alembic head instead** (currently `0016_build_override`).
- Quota unit is **Project** (the "team" shown on the Teams page). Do not introduce organization-level endpoints.
- Platform default env var: `VELA_TEAM_STORAGE_QUOTA_BYTES` (int bytes; unset or invalid = **unlimited**, no hardcoded default — existing dev/test behavior must not change).
- A stored team quota can only **restrict** the platform default (stored > env value is rejected with 400). It can never raise above it.
- Deploy/run rejection rule: `used >= quota` → 400. Upload rejection rule: `used + upload_bytes > quota` → 400.
- New error `TeamStorageQuotaExceededError(ResourceLimitError)` maps to HTTP 400 via the existing `ResourceLimitError` handler in `app/api/errors.py` — do not add a new handler for it. Invalid PATCH values use a new `TeamStorageQuotaError(VelaError)` with its own 400 handler.
- Alert events use `event_type="storage"` with `AlertHistory.container_id = NULL` (that column becomes nullable in Task 1 — required for the rows this feature writes).
- Backend tests: `cd backend && python -m pytest -q`. Frontend gates: `cd frontend && npm run build` and `npm run lint`. E2E: `cd frontend && npm run test:e2e` (stop any dev server on ports 8000/5173 first; `reuseExistingServer` is off).
- MVC: measurement/enforcement/alert logic lives in `app/core/quotas/storage_quota.py` and `app/core/notifications/alert_service.py`; routes stay thin.
- Naming: full words (`storage_quota_bytes`, `environment_quota_bytes`). No new abbreviations.

---

### Task 1: Database schema — `projects.storage_quota_bytes` + nullable `alert_history.container_id`

**Files:**
- Modify: `backend/app/db/models.py` (imports at top; `Project` ~line 159; `AlertHistory` ~line 390)
- Create: `backend/alembic/versions/0018_project_storage_quota.py`
- Test: `backend/tests/test_storage_quota.py` (new file; later tasks append tests here)

**Interfaces:**
- Produces: `Project.storage_quota_bytes: int | None` (ORM column); `AlertHistory.container_id` becomes `str | None`.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_storage_quota.py`:

```python
"""Tests for team (project) storage quota."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AlertHistory, Organization, Project, User


@pytest_asyncio.fixture
async def quota_db() -> AsyncSession:
    """In-memory SQLite session with the full ORM schema."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_project_storage_quota_column(quota_db: AsyncSession) -> None:
    organization = Organization(name="quota org")
    quota_db.add(organization)
    await quota_db.flush()
    project = Project(
        organization_id=organization.id,
        name="Team A",
        is_personal=False,
        storage_quota_bytes=1024,
    )
    quota_db.add(project)
    await quota_db.commit()
    loaded = (await quota_db.execute(select(Project))).scalar_one()
    assert loaded.storage_quota_bytes == 1024


@pytest.mark.asyncio
async def test_alert_history_container_id_nullable(quota_db: AsyncSession) -> None:
    user = User(id=uuid.uuid4(), email="quota@example.com")
    quota_db.add(user)
    await quota_db.flush()
    history = AlertHistory(
        user_id=user.id,
        container_id=None,
        event_type="storage",
        alert_hash="0" * 64,
        sent_at=datetime.now(timezone.utc),
        status="sent",
    )
    quota_db.add(history)
    await quota_db.commit()
    loaded = (
        await quota_db.execute(
            select(AlertHistory).where(AlertHistory.event_type == "storage")
        )
    ).scalar_one()
    assert loaded.container_id is None
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_storage_quota.py -q`
Expected: FAIL — invalid keyword `storage_quota_bytes` and/or NOT NULL violation for `container_id`.

- [x] **Step 3: Implement the model changes**

In `backend/app/db/models.py`, add `BigInteger` to the `sqlalchemy` import block (alphabetical):

```python
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
```

In `class Project` (after the `name` column, before `is_personal`):

```python
    storage_quota_bytes: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
```

In `class AlertHistory`, change:

```python
    container_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
```

to:

```python
    container_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
```

Create `backend/alembic/versions/0018_project_storage_quota.py` (match the style of `0016_build_override.py`; adjust `down_revision` per Global Constraints if `0017_container_metrics.py` does not exist):

```python
"""add project storage quota and nullable alert container id

Revision ID: 0018_project_storage_quota
Revises: 0017_container_metrics
Create Date: 2026-08-16

"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0018_project_storage_quota"
down_revision: str | Sequence[str] | None = "0017_container_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("storage_quota_bytes", sa.BigInteger(), nullable=True),
    )
    with op.batch_alter_table("alert_history") as batch_op:
        batch_op.alter_column(
            "container_id",
            existing_type=sa.String(length=128),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("alert_history") as batch_op:
        batch_op.alter_column(
            "container_id",
            existing_type=sa.String(length=128),
            nullable=False,
        )
    op.drop_column("projects", "storage_quota_bytes")
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_storage_quota.py -q`
Expected: PASS (2 tests).

- [x] **Step 5: Verify the migration round-trips (local dev Postgres)**

Run: `cd backend && python -m alembic upgrade head && python -m alembic downgrade -1 && python -m alembic upgrade head`
Expected: no errors. Skip only if the dev Postgres (`docker compose -f docker-compose.dev.yml up -d`) is not running; note it in the final report.

- [x] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0018_project_storage_quota.py backend/tests/test_storage_quota.py
git commit -m "feat: add project storage quota column and nullable alert container id"
```

---

### Task 2: Container disk size — `ContainerInfo.disk_bytes` from Docker inspect

**Files:**
- Modify: `backend/app/core/models.py` (`ContainerInfo`, ~line 144)
- Modify: `backend/app/core/containers/docker_orchestrator.py` (`_inspect_to_container_info`, ~line 234)
- Modify: `backend/app/core/containers/fake_orchestrator.py` (add `set_disk_bytes` after `seed_container`, ~line 83)
- Test: `backend/tests/test_storage_quota.py` (append)

**Interfaces:**
- Produces: `ContainerInfo.disk_bytes: int` (writable-layer size in bytes; default 0); `FakeContainerOrchestrator.set_disk_bytes(container_id: str, size_bytes: int) -> None`. `DockerOrchestrator.list()` rows carry live `SizeRw` (its `list()` already calls `container.reload()` before mapping).

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_storage_quota.py` (add the import next to the top-of-file imports):

```python
from app.core.containers.docker_orchestrator import _inspect_to_container_info

_INSPECT_BASE = {
    "Id": "abc123",
    "Name": "/vela-app",
    "State": {"Status": "running"},
    "Config": {"Image": "nginx:alpine", "Labels": {}},
    "Created": "2026-04-01T12:00:00Z",
}


def test_inspect_mapping_reads_size_rw() -> None:
    info = _inspect_to_container_info({**_INSPECT_BASE, "SizeRw": 4096})
    assert info.disk_bytes == 4096


def test_inspect_mapping_defaults_disk_bytes_to_zero() -> None:
    info = _inspect_to_container_info(_INSPECT_BASE)
    assert info.disk_bytes == 0
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_storage_quota.py -q`
Expected: the 2 new tests FAIL (`AttributeError: 'ContainerInfo' object has no attribute 'disk_bytes'`); the 2 Task 1 tests still pass.

- [x] **Step 3: Implement**

In `backend/app/core/models.py`, add to `ContainerInfo` (after `volumes`):

```python
    disk_bytes: int = Field(
        default=0,
        description="Writable-layer size in bytes from container inspect (SizeRw).",
    )
```

In `backend/app/core/containers/docker_orchestrator.py`, in `_inspect_to_container_info` add `disk_bytes=int(data.get("SizeRw") or 0),` to the `ContainerInfo(...)` constructor call (after `volumes=`).

In `backend/app/core/containers/fake_orchestrator.py`, add a method to `FakeContainerOrchestrator` after `seed_container`:

```python
    def set_disk_bytes(self, container_id: str, size_bytes: int) -> None:
        """Set the recorded writable-layer size for a seeded container."""
        info = self._containers[container_id]
        self._containers[container_id] = info.model_copy(
            update={"disk_bytes": size_bytes}
        )
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_storage_quota.py tests/test_api_integration.py -q`
Expected: all PASS (the integration suite guards against `ContainerInfo` regressions).

- [x] **Step 5: Commit**

```bash
git add backend/app/core/models.py backend/app/core/containers/docker_orchestrator.py backend/app/core/containers/fake_orchestrator.py backend/tests/test_storage_quota.py
git commit -m "feat: track container writable-layer size (disk_bytes)"
```

---

### Task 3: Quota core — resolution, usage measurement, enforcement, summary

**Files:**
- Create: `backend/app/core/quotas/__init__.py`
- Create: `backend/app/core/quotas/storage_quota.py`
- Modify: `backend/app/core/exceptions.py` (add two error classes after `VolumeUploadQuotaExceededError`, ~line 84)
- Test: `backend/tests/test_storage_quota.py` (append)

**Interfaces:**
- Consumes: `Project.storage_quota_bytes` (Task 1); `ContainerInfo.disk_bytes` (Task 2); `user_uploads_total_bytes(user_id: uuid.UUID) -> int` from `app.core.containers.volume_uploads`.
- Produces (in `app.core.quotas.storage_quota`, re-exported by the package `__init__`):
  - `environment_quota_bytes() -> int | None`
  - `effective_quota_bytes(project: Project) -> int | None`
  - `quota_source(project: Project) -> str` (one of `"team" | "platform" | "unlimited"`)
  - `format_gib(total_bytes: int) -> str`
  - `team_storage_usage(session: AsyncSession, orchestrator: ContainerOrchestrator, project_id: uuid.UUID) -> tuple[int, int]` → `(container_disk_bytes, uploads_bytes)`
  - `enforce_team_storage_capacity(session, orchestrator, project_id: uuid.UUID) -> None` (raises `TeamStorageQuotaExceededError`)
  - `@dataclass(frozen=True) TeamStorageQuotaSummary`: `quota_bytes: int | None`, `used_bytes: int`, `container_disk_bytes: int`, `uploads_bytes: int`, `over_quota: bool`, `source: str`
  - `team_storage_quota_summary(session, orchestrator, project: Project) -> TeamStorageQuotaSummary`
  - `check_team_storage_quotas(session, orchestrator, email_provider) -> None` (alert dispatch lands in Task 6)
  - `reset_over_quota_state() -> None`, `currently_over_quota_projects() -> frozenset[uuid.UUID]`

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_storage_quota.py` (extend the top-of-file imports):

```python
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.containers.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_OWNER_LABEL,
    VELA_PROJECT_LABEL,
)
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus, HealthStatus
from app.core.exceptions import TeamStorageQuotaExceededError
from app.core.models import ContainerInfo
from app.core.quotas import storage_quota
from app.db.models import EmailPreference, ProjectMembership, User
```

(`select`, `TestClient`, and `User` may already be imported — merge instead of duplicating.)

```python
_GB = 1024 ** 3


def _make_info(
    project_id: uuid.UUID | None, disk_bytes: int, owner_id: uuid.UUID
) -> ContainerInfo:
    """Build a fake container record; project-unlabeled when project_id is None."""
    labels = {
        VELA_MANAGED_LABEL: "true",
        VELA_OWNER_LABEL: str(owner_id),
    }
    if project_id is not None:
        labels[VELA_PROJECT_LABEL] = str(project_id)
    return ContainerInfo.model_validate(
        {
            "id": f"cid-{uuid.uuid4().hex[:8]}",
            "name": "vela-quota-test",
            "image": "nginx:alpine",
            "status": ContainerStatus.RUNNING,
            "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            "ports": [],
            "labels": labels,
            "health": HealthStatus.NONE,
            "disk_bytes": disk_bytes,
        }
    )


def test_environment_quota_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELA_TEAM_STORAGE_QUOTA_BYTES", raising=False)
    assert storage_quota.environment_quota_bytes() is None
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", "not-a-number")
    assert storage_quota.environment_quota_bytes() is None
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(_GB))
    assert storage_quota.environment_quota_bytes() == _GB


def test_effective_quota_resolution_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELA_TEAM_STORAGE_QUOTA_BYTES", raising=False)
    assert (
        storage_quota.effective_quota_bytes(Project(storage_quota_bytes=None))
        is None
    )
    assert storage_quota.effective_quota_bytes(Project(storage_quota_bytes=5)) == 5
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", "10")
    assert (
        storage_quota.effective_quota_bytes(Project(storage_quota_bytes=None))
        == 10
    )
    assert storage_quota.effective_quota_bytes(Project(storage_quota_bytes=5)) == 5
    assert storage_quota.effective_quota_bytes(Project(storage_quota_bytes=15)) == 10


def test_quota_source_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELA_TEAM_STORAGE_QUOTA_BYTES", raising=False)
    assert storage_quota.quota_source(Project(storage_quota_bytes=None)) == "unlimited"
    assert storage_quota.quota_source(Project(storage_quota_bytes=1)) == "team"
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(_GB))
    assert storage_quota.quota_source(Project(storage_quota_bytes=None)) == "platform"


@pytest.mark.asyncio
async def test_team_storage_usage_counts_project_containers_and_member_uploads(
    quota_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization = Organization(name="usage org")
    quota_db.add(organization)
    await quota_db.flush()
    project = Project(organization_id=organization.id, name="Team A")
    other = Project(organization_id=organization.id, name="Team B")
    quota_db.add_all([project, other])
    await quota_db.flush()
    member = User(id=uuid.uuid4(), email="member@example.com")
    quota_db.add(member)
    await quota_db.flush()
    quota_db.add(
        ProjectMembership(project_id=project.id, user_id=member.id, role="owner")
    )
    await quota_db.commit()

    uploads: dict[uuid.UUID, int] = {member.id: 50}
    monkeypatch.setattr(
        storage_quota,
        "user_uploads_total_bytes",
        lambda user_id: uploads.get(user_id, 0),
    )

    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(_make_info(project.id, 100, uuid.uuid4()))
    orchestrator.seed_container(_make_info(project.id, 300, uuid.uuid4()))
    orchestrator.seed_container(_make_info(other.id, 999, uuid.uuid4()))
    # Legacy container without a project label, owned by a user whose
    # personal project IS `project` — must count for `project`.
    legacy_owner = User(id=uuid.uuid4(), email="legacy@example.com")
    legacy_owner.personal_project_id = project.id
    quota_db.add(legacy_owner)
    await quota_db.commit()
    orchestrator.seed_container(_make_info(None, 25, legacy_owner.id))

    disk, uploads_bytes = await storage_quota.team_storage_usage(
        quota_db, orchestrator, project.id
    )
    assert disk == 425
    assert uploads_bytes == 50

    disk_other, _ = await storage_quota.team_storage_usage(
        quota_db, orchestrator, other.id
    )
    assert disk_other == 999


@pytest.mark.asyncio
async def test_enforce_team_storage_capacity(
    quota_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization = Organization(name="enforce org")
    quota_db.add(organization)
    await quota_db.flush()
    project = Project(
        organization_id=organization.id,
        name="Full team",
        storage_quota_bytes=400,
    )
    quota_db.add(project)
    await quota_db.commit()
    monkeypatch.setattr(storage_quota, "user_uploads_total_bytes", lambda user_id: 0)

    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(_make_info(project.id, 400, uuid.uuid4()))

    with pytest.raises(TeamStorageQuotaExceededError) as excinfo:
        await storage_quota.enforce_team_storage_capacity(
            quota_db, orchestrator, project.id
        )
    assert "Full team" in str(excinfo.value)
    assert "storage quota" in str(excinfo.value)

    # Unlimited team: no error with the same usage.
    unlimited = Project(organization_id=organization.id, name="Free team")
    quota_db.add(unlimited)
    await quota_db.flush()
    orchestrator.seed_container(_make_info(unlimited.id, 10_000, uuid.uuid4()))
    await storage_quota.enforce_team_storage_capacity(
        quota_db, orchestrator, unlimited.id
    )
```

Also append an autouse module fixture (right after the imports/helpers, before the first test) so later tasks' tests start clean:

```python
@pytest.fixture(autouse=True)
def _reset_over_quota_state() -> None:
    storage_quota.reset_over_quota_state()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_storage_quota.py -q`
Expected: the new tests FAIL (`ModuleNotFoundError: No module named 'app.core.quotas'`); earlier tasks' tests still pass.

- [x] **Step 3: Add the exceptions**

In `backend/app/core/exceptions.py`, after `VolumeUploadQuotaExceededError`:

```python
class TeamStorageQuotaExceededError(ResourceLimitError):
    """A deployment or upload would push the team over its storage quota."""


class TeamStorageQuotaError(VelaError):
    """Invalid team storage quota value (e.g. above the platform limit)."""
```

- [x] **Step 4: Implement the quotas package**

Create `backend/app/core/quotas/storage_quota.py`:

```python
"""Team (project) storage quota: measurement, enforcement, over-quota alerts."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.docker_orchestrator import (
    VELA_OWNER_LABEL,
    VELA_PROJECT_LABEL,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.containers.volume_uploads import user_uploads_total_bytes
from app.core.exceptions import TeamStorageQuotaExceededError
from app.core.models import ContainerInfo
from app.core.notifications.alert_service import AlertService
from app.core.notifications.email_provider import EmailProvider
from app.db.models import Project, ProjectMembership, User

logger = logging.getLogger(__name__)

GIB = 1024 ** 3

_over_quota_project_ids: set[uuid.UUID] = set()


def format_gib(total_bytes: int) -> str:
    return f"{total_bytes / GIB:.1f} GB"


def environment_quota_bytes() -> int | None:
    """Platform storage quota from VELA_TEAM_STORAGE_QUOTA_BYTES (None = unlimited)."""
    raw = os.environ.get("VELA_TEAM_STORAGE_QUOTA_BYTES", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid VELA_TEAM_STORAGE_QUOTA_BYTES %r", raw)
        return None
    return value if value > 0 else None


def effective_quota_bytes(project: Project) -> int | None:
    """Team quota, clamped to the platform default (stored can only restrict)."""
    stored = project.storage_quota_bytes
    environment = environment_quota_bytes()
    if stored is None:
        return environment
    if environment is None:
        return stored
    return min(stored, environment)


def quota_source(project: Project) -> str:
    """Where the effective quota comes from: 'team', 'platform', or 'unlimited'."""
    if project.storage_quota_bytes is not None:
        return "team"
    return "platform" if environment_quota_bytes() is not None else "unlimited"


def reset_over_quota_state() -> None:
    _over_quota_project_ids.clear()


def currently_over_quota_projects() -> frozenset[uuid.UUID]:
    return frozenset(_over_quota_project_ids)


async def _member_user_ids(
    session: AsyncSession, project_id: uuid.UUID
) -> list[uuid.UUID]:
    statement = select(ProjectMembership.user_id).where(
        ProjectMembership.project_id == project_id
    )
    return list((await session.execute(statement)).scalars().all())


async def _users_with_personal_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    candidate_user_ids: set[uuid.UUID],
) -> set[uuid.UUID]:
    if not candidate_user_ids:
        return set()
    statement = select(User.id).where(
        User.personal_project_id == project_id,
        User.id.in_(candidate_user_ids),
    )
    return set((await session.execute(statement)).scalars().all())


async def usage_from_containers(
    session: AsyncSession,
    containers: list[ContainerInfo],
    project_id: uuid.UUID,
) -> tuple[int, int]:
    """(container_disk_bytes, uploads_bytes) for one team.

    Container disk counts every container labeled with the project, plus
    project-unlabeled containers whose owner's personal project is this
    project (same fallback as resolve_container_project_id).
    """
    candidate_owners: set[uuid.UUID] = set()
    for container in containers:
        if not container.labels.get(VELA_PROJECT_LABEL):
            raw_owner = container.labels.get(VELA_OWNER_LABEL)
            if raw_owner:
                try:
                    candidate_owners.add(uuid.UUID(raw_owner))
                except ValueError:
                    pass
    personal_owners = await _users_with_personal_project(
        session, project_id, candidate_owners
    )
    labeled = str(project_id)
    disk = sum(
        container.disk_bytes
        for container in containers
        if container.labels.get(VELA_PROJECT_LABEL) == labeled
        or (
            not container.labels.get(VELA_PROJECT_LABEL)
            and str(container.labels.get(VELA_OWNER_LABEL, ""))
            in {str(owner_id) for owner_id in personal_owners}
        )
    )
    member_ids = await _member_user_ids(session, project_id)
    uploads = sum(user_uploads_total_bytes(member_id) for member_id in member_ids)
    return disk, uploads


async def team_storage_usage(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    project_id: uuid.UUID,
) -> tuple[int, int]:
    """(container_disk_bytes, uploads_bytes) currently used by a team."""
    containers = await orchestrator.list()
    return await usage_from_containers(session, containers, project_id)


async def enforce_team_storage_capacity(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    project_id: uuid.UUID,
) -> None:
    """Reject new deployments once the team has reached its storage quota."""
    project = await session.get(Project, project_id)
    if project is None:
        return
    quota = effective_quota_bytes(project)
    if quota is None:
        return
    disk, uploads = await team_storage_usage(session, orchestrator, project_id)
    used = disk + uploads
    if used >= quota:
        raise TeamStorageQuotaExceededError(
            f"This deployment would exceed the {project.name} team's "
            f"{format_gib(quota)} storage quota ({format_gib(used)} used). "
            "Stop or remove containers, or free uploaded folders."
        )


@dataclass(frozen=True)
class TeamStorageQuotaSummary:
    quota_bytes: int | None
    used_bytes: int
    container_disk_bytes: int
    uploads_bytes: int
    over_quota: bool
    source: str


async def team_storage_quota_summary(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    project: Project,
) -> TeamStorageQuotaSummary:
    """Full usage/quota snapshot for a team."""
    quota = effective_quota_bytes(project)
    disk, uploads = await team_storage_usage(session, orchestrator, project.id)
    used = disk + uploads
    return TeamStorageQuotaSummary(
        quota_bytes=quota,
        used_bytes=used,
        container_disk_bytes=disk,
        uploads_bytes=uploads,
        over_quota=quota is not None and used >= quota,
        source=quota_source(project),
    )


async def check_team_storage_quotas(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    email_provider: EmailProvider,
) -> None:
    """Alert members on the rising edge when a team exceeds its storage quota.

    State resets on API restart: a team already over quota re-alarms once
    after a restart (same reset behavior as container state-change alerts).
    """
    try:
        containers = await orchestrator.list()
    except Exception:
        logger.warning(
            "Skipping team storage quota check: container list unavailable",
            exc_info=True,
        )
        return
    projects = list((await session.execute(select(Project))).scalars().all())
    for project in projects:
        quota = effective_quota_bytes(project)
        if quota is None:
            _over_quota_project_ids.discard(project.id)
            continue
        disk, uploads = await usage_from_containers(session, containers, project.id)
        used = disk + uploads
        if used >= quota:
            if project.id in _over_quota_project_ids:
                continue
            _over_quota_project_ids.add(project.id)
            member_ids = await _member_user_ids(session, project.id)
            alert_service = AlertService(email_provider, session)
            for member_id in member_ids:
                await alert_service.send_project_storage_alert(
                    user_id=member_id,
                    project_id=project.id,
                    project_name=project.name,
                    used_bytes=used,
                    quota_bytes=quota,
                )
        else:
            _over_quota_project_ids.discard(project.id)
```

Create `backend/app/core/quotas/__init__.py` (style of `app/core/security/__init__.py`):

```python
"""Team storage quota: measurement, enforcement, alerts."""

from app.core.quotas.storage_quota import (
    TeamStorageQuotaSummary,
    check_team_storage_quotas,
    currently_over_quota_projects,
    effective_quota_bytes,
    enforce_team_storage_capacity,
    environment_quota_bytes,
    format_gib,
    quota_source,
    reset_over_quota_state,
    team_storage_quota_summary,
    team_storage_usage,
    usage_from_containers,
)

__all__ = [
    "TeamStorageQuotaSummary",
    "check_team_storage_quotas",
    "currently_over_quota_projects",
    "effective_quota_bytes",
    "enforce_team_storage_capacity",
    "environment_quota_bytes",
    "format_gib",
    "quota_source",
    "reset_over_quota_state",
    "team_storage_quota_summary",
    "team_storage_usage",
    "usage_from_containers",
]
```

NOTE: `check_team_storage_quotas` calls `AlertService.send_project_storage_alert`, which only exists after Task 6 Step 3. In this task the module still imports cleanly (the call resolves at runtime); `usage_from_containers` is kept public on purpose so the dashboard-usage integration (Task 10) can reuse it.

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_storage_quota.py -q`
Expected: all PASS. (The `check_team_storage_quotas` rising-edge test arrives in Task 6.)

- [x] **Step 6: Commit**

```bash
git add backend/app/core/quotas backend/app/core/exceptions.py backend/tests/test_storage_quota.py
git commit -m "feat: add team storage quota core (resolution, usage, enforcement)"
```

---

### Task 4: Enforce the quota on the run, deploy, and volume-upload routes

**Files:**
- Modify: `backend/app/api/routes/containers.py` — imports at top; `deploy` (~line 584); `upload_volume_folder` (~line 612); `run_from_user_source` (~line 667)
- Test: `backend/tests/test_storage_quota.py` (append)

**Interfaces:**
- Consumes: `enforce_team_storage_capacity(session, orchestrator, project_id)`, `team_storage_usage(...)`, `effective_quota_bytes(project)`, `format_gib(...)` (Task 3); `get_personal_project_id(session, user)` from `app.core.projects.repository` (already imported in containers.py).
- Produces: `POST /api/containers/run` and `POST /api/containers/deploy` return 400 with a `detail` containing the team name and "storage quota" when the team is at/over quota; `POST /api/containers/volume-uploads` returns 400 when the upload would push the caller's personal team over quota. All other request behavior unchanged.

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_storage_quota.py`:

```python
def test_run_blocked_when_team_quota_exceeded(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", "1024")
    # cid-1 carries the seeded user's owner label and no project label, so it
    # counts for their personal project.
    fake_orchestrator.set_disk_bytes("cid-1", 2048)
    assert seeded_user.personal_project_id is not None
    response = api_client.post(
        "/api/containers/run",
        json={"source_kind": "image", "image_ref": "nginx:alpine"},
    )
    assert response.status_code == 400
    assert "storage quota" in response.json()["detail"]


def test_run_allowed_under_team_quota(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(10 * _GB))
    fake_orchestrator.set_disk_bytes("cid-1", 2048)
    response = api_client.post(
        "/api/containers/run",
        json={"source_kind": "image", "image_ref": "nginx:alpine"},
    )
    assert response.status_code == 200


def test_deploy_blocked_when_team_quota_exceeded(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", "1024")
    fake_orchestrator.set_disk_bytes("cid-1", 2048)
    response = api_client.post(
        "/api/containers/deploy",
        json={
            "image": "nginx:alpine",
            "project_id": str(seeded_user.personal_project_id),
        },
    )
    assert response.status_code == 400
    assert "storage quota" in response.json()["detail"]


def test_upload_blocked_when_team_storage_quota_exceeded(
    api_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VELA_VOLUME_UPLOAD_USER_QUOTA_BYTES", str(150 * 1024 ** 2))
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(1024 * 1024))

    first = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("folder/a.bin", b"x" * (1024 * 1024)))],
    )
    assert first.status_code == 200, first.text

    second = api_client.post(
        "/api/containers/volume-uploads",
        files=[("files", ("folder/b.bin", b"x" * (1024 * 1024 + 8)))],
    )
    assert second.status_code == 400
    assert "storage quota" in second.json()["detail"]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_storage_quota.py -q`
Expected: the 4 new tests FAIL (they get 200 — no enforcement wired yet).

- [x] **Step 3: Wire enforcement into the routes**

In `backend/app/api/routes/containers.py`:

Extend the imports (merge into the existing import blocks):

```python
from app.core.quotas import (
    effective_quota_bytes,
    enforce_team_storage_capacity,
    format_gib,
    team_storage_usage,
)
```

add `TeamStorageQuotaExceededError` to the existing `app.core.exceptions` import list, and add `Project` to the `app.db.models` import (`from app.db.models import Project, User`).

In `deploy`, right after the `project_id = await _resolve_deploy_project_id_for_config(...)` line (before `_apply_deploy_labels`):

```python
    await enforce_team_storage_capacity(session, orchestrator, project_id)
```

In `run_from_user_source`, right after `project_id = await _resolve_deploy_project_id(session, current_user, body)`:

```python
    await enforce_team_storage_capacity(session, orchestrator, project_id)
```

In `upload_volume_folder`, change the signature to:

```python
@router.post("/volume-uploads", response_model=VolumeUploadResponse)
async def upload_volume_folder(
    files: Annotated[list[UploadFile], File(...)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> VolumeUploadResponse:
```

and after the per-file `for upload in files:` loop, before `save_volume_upload(...)`, insert:

```python
    personal_project_id = await get_personal_project_id(session, current_user)
    personal_project = await session.get(Project, personal_project_id)
    team_quota = (
        effective_quota_bytes(personal_project)
        if personal_project is not None
        else None
    )
    if team_quota is not None:
        disk_bytes, uploads_bytes = await team_storage_usage(
            session, orchestrator, personal_project_id
        )
        used_bytes = disk_bytes + uploads_bytes
        if used_bytes + total_bytes > team_quota:
            raise TeamStorageQuotaExceededError(
                f"Upload would exceed the team's {format_gib(team_quota)} "
                f"storage quota ({format_gib(used_bytes)} used). "
                "Use a smaller folder or remove unused uploads."
            )
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_storage_quota.py tests/test_api_integration.py -q`
Expected: all PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/api/routes/containers.py backend/tests/test_storage_quota.py
git commit -m "feat: enforce team storage quota on run, deploy, and uploads"
```

---

### Task 5: Storage-quota settings endpoints + `ProjectPublic` quota field

**Files:**
- Modify: `backend/app/api/schemas.py` (`ProjectPublic` ~line 452; new schemas after `MyProjectRolePublic` ~line 500)
- Modify: `backend/app/api/routes/projects.py` — `_project_public` (46-60) + its 4 call sites (70, 92, 133, 165); new routes after `get_project` (~line 171)
- Modify: `backend/app/api/errors.py` (400 handler for `TeamStorageQuotaError`)
- Test: `backend/tests/test_storage_quota.py` (append)

**Interfaces:**
- Consumes: `team_storage_quota_summary(session, orchestrator, project) -> TeamStorageQuotaSummary`, `environment_quota_bytes()`, `format_gib(...)` (Task 3); `require_membership`, `require_project` from `app.core.projects.repository` (already imported in projects.py).
- Produces:
  - `GET /api/projects/{project_id}/storage-quota` → 200 `ProjectStorageQuotaPublic` for members; 403 for non-members.
  - `PATCH /api/projects/{project_id}/storage-quota` body `{"storage_quota_bytes": int | null}` → 200 updated `ProjectStorageQuotaPublic`; 403 non-owner; 400 when the value exceeds the platform default (`TeamStorageQuotaError`).
  - `ProjectPublic.storage_quota_bytes: int | None` (present in project list/create/detail/accept responses).

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_storage_quota.py` (add `from typing import Any` to the imports):

```python
def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password-min-8-chars"},
    )
    assert response.status_code == 201, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def _personal_project_id(client: TestClient) -> str:
    return next(
        project["id"]
        for project in client.get("/api/projects/").json()
        if project["is_personal"]
    )


def test_storage_quota_get_for_member(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolate the upload-scan directory so local dev uploads can't skew the total.
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(1024 * 1024))
    fake_orchestrator.set_disk_bytes("cid-1", 10 * 1024)
    project_id = seeded_user.personal_project_id
    assert project_id is not None

    response = api_client.get(f"/api/projects/{project_id}/storage-quota")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["quota_bytes"] == 1024 * 1024
    assert body["container_disk_bytes"] == 10 * 1024
    assert body["uploads_bytes"] == 0
    assert body["used_bytes"] == 10 * 1024
    assert body["over_quota"] is False
    assert body["source"] == "platform"


def test_storage_quota_requires_membership(
    db_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(_GB))
    with TestClient(db_app) as owner_client, TestClient(db_app) as stranger_client:
        _register(owner_client, "quota-owner@example.com")
        owner_project_id = _personal_project_id(owner_client)

        _register(stranger_client, "quota-stranger@example.com")
        response = stranger_client.get(
            f"/api/projects/{owner_project_id}/storage-quota"
        )
        assert response.status_code == 403


def test_patch_storage_quota_rejects_above_platform_limit(
    db_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(10 * 1024 * 1024))
    with TestClient(db_app) as client:
        _register(client, "quota-patch@example.com")
        project_id = _personal_project_id(client)
        response = client.patch(
            f"/api/projects/{project_id}/storage-quota",
            json={"storage_quota_bytes": 20 * 1024 * 1024},
        )
        assert response.status_code == 400
        assert "platform limit" in response.json()["detail"]


def test_patch_storage_quota_owner_sets_and_clears(
    db_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(10 * _GB))
    with TestClient(db_app) as client:
        _register(client, "quota-set@example.com")
        project_id = _personal_project_id(client)

        response = client.patch(
            f"/api/projects/{project_id}/storage-quota",
            json={"storage_quota_bytes": 5 * _GB},
        )
        assert response.status_code == 200, response.text
        assert response.json()["quota_bytes"] == 5 * _GB
        assert response.json()["source"] == "team"

        listed = client.get("/api/projects/").json()
        assert next(
            project for project in listed if project["id"] == project_id
        )["storage_quota_bytes"] == 5 * _GB

        response = client.patch(
            f"/api/projects/{project_id}/storage-quota",
            json={"storage_quota_bytes": None},
        )
        assert response.status_code == 200
        assert response.json()["quota_bytes"] == 10 * _GB
        assert response.json()["source"] == "platform"


def test_patch_storage_quota_forbidden_for_non_owner(db_app: Any) -> None:
    with TestClient(db_app) as owner_client, TestClient(db_app) as member_client:
        _register(owner_client, "quota-team-owner@example.com")
        create_response = owner_client.post(
            "/api/projects/", json={"name": "Quota team"}
        )
        assert create_response.status_code == 201, create_response.text
        team_id = create_response.json()["id"]

        _register(member_client, "quota-team-member@example.com")
        invitation = owner_client.post(
            f"/api/projects/{team_id}/invitations",
            json={"email": "quota-team-member@example.com", "role": "viewer"},
        )
        assert invitation.status_code == 201, invitation.text
        incoming = member_client.get("/api/projects/invitations/incoming").json()
        accept = member_client.post(
            f"/api/projects/invitations/{incoming[0]['id']}/accept"
        )
        assert accept.status_code == 200, accept.text

        response = member_client.patch(
            f"/api/projects/{team_id}/storage-quota",
            json={"storage_quota_bytes": _GB},
        )
        assert response.status_code == 403
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_storage_quota.py -q`
Expected: the 5 new tests FAIL (404 on `/storage-quota`; project responses lack `storage_quota_bytes`).

- [x] **Step 3: Add the schemas**

In `backend/app/api/schemas.py`, extend `ProjectPublic`:

```python
class ProjectPublic(BaseModel):
    id: uuid.UUID
    name: str
    is_personal: bool
    role: ProjectRoleLiteral
    owner_email: str
    storage_quota_bytes: int | None = None
```

After `MyProjectRolePublic`:

```python
class ProjectStorageQuotaPublic(BaseModel):
    quota_bytes: int | None
    used_bytes: int
    container_disk_bytes: int
    uploads_bytes: int
    over_quota: bool
    source: str


class ProjectStorageQuotaUpdate(BaseModel):
    storage_quota_bytes: int | None = Field(default=None, ge=1)
```

- [x] **Step 4: Register the 400 handler for `TeamStorageQuotaError`**

In `backend/app/api/errors.py`, add `TeamStorageQuotaError` to the `app.core.exceptions` import list and add a handler next to the other 400 handlers (e.g. right after `unsupported_project_handler`):

```python
    @app.exception_handler(TeamStorageQuotaError)
    async def team_storage_quota_error_handler(
        _request: Request, exc: TeamStorageQuotaError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )
```

- [x] **Step 5: Implement the routes**

In `backend/app/api/routes/projects.py`, extend the imports (merge into existing blocks):

```python
from app.api.deps import get_orchestrator  # if get_db/get_current_user are imported from app.api.deps
from app.api.schemas import ProjectStorageQuotaPublic, ProjectStorageQuotaUpdate
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import ProjectAccessDeniedError, TeamStorageQuotaError
from app.core.quotas import (
    TeamStorageQuotaSummary,
    environment_quota_bytes,
    format_gib,
    team_storage_quota_summary,
)
from app.core.projects.enums import ProjectRole
from app.db.models import Project
```

Extend `_project_public` with the new field and pass it at all 4 call sites:

```python
def _project_public(
    *,
    project_id: uuid.UUID,
    name: str,
    is_personal: bool,
    role: str,
    owner_email: str,
    storage_quota_bytes: int | None,
) -> ProjectPublic:
    return ProjectPublic(
        id=project_id,
        name=name,
        is_personal=is_personal,
        role=role,
        owner_email=owner_email,
        storage_quota_bytes=storage_quota_bytes,
    )
```

- call site in `list_user_projects`: `storage_quota_bytes=row.project.storage_quota_bytes`
- call site in `create_user_project`: `storage_quota_bytes=row.project.storage_quota_bytes`
- call site in `accept_project_invitation`: `storage_quota_bytes=row.project.storage_quota_bytes`
- call site in `get_project`: `storage_quota_bytes=project.storage_quota_bytes`

Add the two routes after `get_project` (before `list_project_members`):

```python
def _storage_quota_public(summary: TeamStorageQuotaSummary) -> ProjectStorageQuotaPublic:
    return ProjectStorageQuotaPublic(
        quota_bytes=summary.quota_bytes,
        used_bytes=summary.used_bytes,
        container_disk_bytes=summary.container_disk_bytes,
        uploads_bytes=summary.uploads_bytes,
        over_quota=summary.over_quota,
        source=summary.source,
    )


@router.get("/{project_id}/storage-quota", response_model=ProjectStorageQuotaPublic)
async def get_project_storage_quota(
    project_id: uuid.UUID,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectStorageQuotaPublic:
    await require_membership(
        session, project_id=project_id, user_id=current_user.id
    )
    project = await require_project(session, project_id)
    summary = await team_storage_quota_summary(session, orchestrator, project)
    return _storage_quota_public(summary)


@router.patch(
    "/{project_id}/storage-quota", response_model=ProjectStorageQuotaPublic
)
async def update_project_storage_quota(
    project_id: uuid.UUID,
    body: ProjectStorageQuotaUpdate,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectStorageQuotaPublic:
    membership = await require_membership(
        session, project_id=project_id, user_id=current_user.id
    )
    if ProjectRole(membership.role) != ProjectRole.OWNER:
        raise ProjectAccessDeniedError(
            "Only the team owner can change the storage quota."
        )
    project = await require_project(session, project_id)
    requested = body.storage_quota_bytes
    if requested is not None:
        platform_quota = environment_quota_bytes()
        if platform_quota is not None and requested > platform_quota:
            raise TeamStorageQuotaError(
                "Team quota cannot exceed the platform limit "
                f"of {format_gib(platform_quota)}."
            )
        project.storage_quota_bytes = requested
        await session.commit()
        await session.refresh(project)
    summary = await team_storage_quota_summary(session, orchestrator, project)
    return _storage_quota_public(summary)
```

(`TeamStorageQuotaSummary` goes in the `app.core.quotas` import list. If `ProjectAccessDeniedError` / `require_membership` / `require_project` are already imported in this file, merge — do not duplicate.)

- [x] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_storage_quota.py tests/test_projects_api.py -q`
Expected: all PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes/projects.py backend/app/api/errors.py backend/tests/test_storage_quota.py
git commit -m "feat: add team storage quota settings endpoints"
```

---

### Task 6: Storage alert — `send_project_storage_alert` + rising-edge check + monitor-loop hook

**Files:**
- Modify: `backend/app/core/notifications/alert_service.py` (new method after `send_container_alert`, ~line 159)
- Modify: `backend/app/core/notifications/container_monitor.py` (constant ~line 36; import; hook in `run_monitoring_loop`)
- Test: `backend/tests/test_storage_quota.py` (append)

**Interfaces:**
- Consumes: `AlertService._resolve_effective_preferences` / `_should_send_alert` / `_hash_event` (existing); `AlertHistory` with nullable `container_id` (Task 1); `check_team_storage_quotas` (Task 3).
- Produces: `AlertService.send_project_storage_alert(user_id: uuid.UUID, project_id: uuid.UUID, project_name: str, used_bytes: int, quota_bytes: int) -> bool` — emails the member when alerts are enabled (independent of the `alert_types` list), dedupes via the standard 10-minute window, and writes one `AlertHistory` row per member with `event_type="storage"`, `container_id=None`. The monitoring loop runs `check_team_storage_quotas` every 20 passes (~5 min at the default 15s interval).

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_storage_quota.py` (imports for `AlertService`, `ConsoleProvider`, `EmailPreference` — merge into the existing import blocks):

```python
@pytest.mark.asyncio
async def test_check_team_storage_quotas_alerts_rising_edge_once(
    quota_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.notifications.alert_service import AlertService
    from app.core.notifications.email_provider import ConsoleProvider

    organization = Organization(name="alert org")
    quota_db.add(organization)
    await quota_db.flush()
    project = Project(
        organization_id=organization.id,
        name="Alert team",
        storage_quota_bytes=400,
    )
    quota_db.add(project)
    await quota_db.flush()
    member = User(id=uuid.uuid4(), email="alert-member@example.com")
    quota_db.add(member)
    await quota_db.flush()
    quota_db.add(
        ProjectMembership(project_id=project.id, user_id=member.id, role="owner")
    )
    await quota_db.commit()
    monkeypatch.setattr(storage_quota, "user_uploads_total_bytes", lambda user_id: 0)

    orchestrator = FakeContainerOrchestrator()
    container = _make_info(project.id, 100, member.id)
    orchestrator.seed_container(container)
    orchestrator.set_disk_bytes(container.id, 500)

    # Patch AlertService so the test asserts on dispatch decisions, not email I/O.
    dispatched: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def fake_send(
        self: AlertService,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        project_name: str,
        used_bytes: int,
        quota_bytes: int,
    ) -> bool:
        dispatched.append((user_id, project_id))
        return True

    monkeypatch.setattr(
        AlertService, "send_project_storage_alert", fake_send, raising=True
    )

    await storage_quota.check_team_storage_quotas(
        quota_db, orchestrator, ConsoleProvider()
    )
    assert storage_quota.currently_over_quota_projects() == frozenset(
        {project.id}
    )
    assert dispatched == [(member.id, project.id)]

    # Second pass while still over: no duplicate dispatch.
    await storage_quota.check_team_storage_quotas(
        quota_db, orchestrator, ConsoleProvider()
    )
    assert dispatched == [(member.id, project.id)]

    # Back under the limit clears the over-quota state.
    orchestrator.set_disk_bytes(container.id, 100)
    await storage_quota.check_team_storage_quotas(
        quota_db, orchestrator, ConsoleProvider()
    )
    assert project.id not in storage_quota.currently_over_quota_projects()


@pytest.mark.asyncio
async def test_project_storage_alert_sent_and_deduplicated(
    quota_db: AsyncSession,
) -> None:
    from app.core.notifications.email_provider import ConsoleProvider

    from app.core.notifications.alert_service import AlertService

    user = User(id=uuid.uuid4(), email="storage-alert@example.com")
    quota_db.add(user)
    await quota_db.flush()
    quota_db.add(
        EmailPreference(
            user_id=user.id,
            email="storage-alert@example.com",
            alerts_enabled=True,
            alert_types=[],
            alert_frequency="immediate",
        )
    )
    await quota_db.commit()

    service = AlertService(ConsoleProvider(), quota_db)
    project_id = uuid.uuid4()
    assert (
        await service.send_project_storage_alert(
            user_id=user.id,
            project_id=project_id,
            project_name="Alert team",
            used_bytes=500,
            quota_bytes=400,
        )
        is True
    )
    assert (
        await service.send_project_storage_alert(
            user_id=user.id,
            project_id=project_id,
            project_name="Alert team",
            used_bytes=500,
            quota_bytes=400,
        )
        is False
    )
    rows = (
        await quota_db.execute(
            select(AlertHistory).where(AlertHistory.event_type == "storage")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].container_id is None
    assert rows[0].email_sent_to == "storage-alert@example.com"


@pytest.mark.asyncio
async def test_project_storage_alert_respects_disabled_notifications(
    quota_db: AsyncSession,
) -> None:
    from app.core.notifications.alert_service import AlertService
    from app.core.notifications.email_provider import ConsoleProvider

    user = User(id=uuid.uuid4(), email="quiet@example.com")
    quota_db.add(user)
    await quota_db.flush()
    quota_db.add(
        EmailPreference(
            user_id=user.id,
            email="quiet@example.com",
            alerts_enabled=False,
            alert_types=["stop"],
            alert_frequency="immediate",
        )
    )
    await quota_db.commit()

    service = AlertService(ConsoleProvider(), quota_db)
    assert (
        await service.send_project_storage_alert(
            user_id=user.id,
            project_id=uuid.uuid4(),
            project_name="Quiet team",
            used_bytes=500,
            quota_bytes=400,
        )
        is False
    )
    rows = (
        await quota_db.execute(
            select(AlertHistory).where(AlertHistory.event_type == "storage")
        )
    ).scalars().all()
    assert rows == []
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_storage_quota.py -q`
Expected: the 3 new tests FAIL (`AttributeError: 'AlertService' object has no attribute 'send_project_storage_alert'`). Note the rising-edge test monkeypatches that same method, so it fails at the patch target lookup for the same reason.

- [x] **Step 3: Implement `send_project_storage_alert`**

In `backend/app/core/notifications/alert_service.py`, add after `send_container_alert` (same structure — `try/except`, preferences gating without the `alert_types` filter, 10-minute dedup via the existing helper):

```python
    async def send_project_storage_alert(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        project_name: str,
        used_bytes: int,
        quota_bytes: int,
    ) -> bool:
        """Send a team storage over-quota alert if notifications are enabled."""
        try:
            effective = await self._resolve_effective_preferences(user_id)
            if effective is None or not effective.alerts_enabled:
                logger.debug("Alerts disabled for user %s", user_id)
                return False
            if effective.alert_frequency != DEFAULT_ALERT_FREQUENCY:
                logger.debug(
                    "Skipping storage alert for user %s: frequency %r is not "
                    "supported yet",
                    user_id,
                    effective.alert_frequency,
                )
                return False

            event_key = f"project:{project_id}"
            if not await self._should_send_alert(user_id, event_key, "storage"):
                return False

            alert = EmailAlert(
                to=effective.email,
                container_name=project_name,
                event_type="storage",
                timestamp=datetime.now(timezone.utc),
                details=(
                    f"Team {project_name} is over its storage quota: "
                    f"{used_bytes / (1024 ** 3):.1f} GB used of "
                    f"{quota_bytes / (1024 ** 3):.1f} GB. "
                    "Stop or remove containers, or free uploaded folders."
                ),
            )
            success = await self.email_provider.send_alert(alert)
            if not success:
                return False

            self.session.add(
                AlertHistory(
                    user_id=user_id,
                    container_id=None,
                    event_type="storage",
                    alert_hash=self._hash_event(user_id, event_key, "storage"),
                    sent_at=datetime.now(timezone.utc),
                    email_sent_to=effective.email,
                    status="sent",
                )
            )
            await self.session.commit()
            return True
        except Exception:
            logger.exception(
                "Error sending project storage alert for user %s", user_id
            )
            return False
```

- [x] **Step 4: Hook the check into the monitoring loop**

In `backend/app/core/notifications/container_monitor.py`:

Add the import with the other app imports:

```python
from app.core.quotas import check_team_storage_quotas
```

Add a constant after `ALERT_LOG_TAIL_LINES`:

```python
STORAGE_QUOTA_CHECK_EVERY_N_PASSES = 20
```

In `run_monitoring_loop`, add a counter before the `while True:` and run the check every N passes inside the existing per-pass session:

```python
    storage_quota_passes = 0
    while True:
        try:
            orchestrator = get_orchestrator()
            async with session_factory() as session:
                await monitor_containers_once(
                    orchestrator, email_provider, session, state
                )
                storage_quota_passes += 1
                if storage_quota_passes % STORAGE_QUOTA_CHECK_EVERY_N_PASSES == 0:
                    await check_team_storage_quotas(
                        session, orchestrator, email_provider
                    )
```

(Keep the existing `except` clauses unchanged — the check has its own `try` around the container list, and the loop's broad `except Exception` covers the rest.) The hook is 4 lines of cadence logic and is not unit-tested; `check_team_storage_quotas` itself is covered above.

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_storage_quota.py tests/test_email_alerts.py -q`
Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/core/notifications/alert_service.py backend/app/core/notifications/container_monitor.py backend/tests/test_storage_quota.py
git commit -m "feat: alert team members when storage quota is exceeded"
```

---

### Task 7: Frontend — API client + Storage section on the Teams page

**Files:**
- Modify: `frontend/src/api/client.ts` (`Project` type ~line 856; type + 2 functions near the other project API functions ~line 889)
- Modify: `frontend/src/pages/TeamsPage.tsx` (imports, helper, state, `loadTeamDetail`, `onSaveQuota`, section JSX)
- Modify: `frontend/src/index.css` (storage classes near the existing `.teams-page__*` rules)

**Interfaces:**
- Consumes: `GET`/`PATCH /api/projects/{id}/storage-quota` (Task 5); `apiGet`/`apiPatch` from client.ts.
- Produces: `Project.storage_quota_bytes: number | null`; `type ProjectStorageQuota`; `getProjectStorageQuota(projectId: string): Promise<ProjectStorageQuota>`; `updateProjectStorageQuota(projectId: string, storageQuotaBytes: number | null): Promise<ProjectStorageQuota>`; a "Storage" section on the selected team's detail (usage line + progress bar + over-quota warning + owner-only GB form).

- [x] **Step 1: Extend `client.ts`**

Update the `Project` type:

```ts
export type Project = {
  id: string
  name: string
  is_personal: boolean
  role: ProjectRole
  owner_email: string
  storage_quota_bytes: number | null
}
```

Add the type next to the other project types:

```ts
export type ProjectStorageQuota = {
  quota_bytes: number | null
  used_bytes: number
  container_disk_bytes: number
  uploads_bytes: number
  over_quota: boolean
  source: 'team' | 'platform' | 'unlimited'
}
```

Add the functions next to `listProjects`:

```ts
export async function getProjectStorageQuota(
  projectId: string,
): Promise<ProjectStorageQuota> {
  return apiGet<ProjectStorageQuota>(
    `/api/projects/${encodeURIComponent(projectId)}/storage-quota`,
  )
}

export async function updateProjectStorageQuota(
  projectId: string,
  storageQuotaBytes: number | null,
): Promise<ProjectStorageQuota> {
  return apiPatch<ProjectStorageQuota, { storage_quota_bytes: number | null }>(
    `/api/projects/${encodeURIComponent(projectId)}/storage-quota`,
    { storage_quota_bytes: storageQuotaBytes },
  )
}
```

- [x] **Step 2: Update `TeamsPage.tsx`**

Imports: add `getProjectStorageQuota`, `updateProjectStorageQuota`, and `type ProjectStorageQuota` to the existing `../api/client` import block.

Add a helper near `formatRoleLabel`:

```ts
function formatGib(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}
```

New state next to `members`:

```ts
  const [storageQuota, setStorageQuota] = useState<ProjectStorageQuota | null>(
    null,
  )
  const [quotaInput, setQuotaInput] = useState('')
```

In `loadTeamDetail`, replace the single `listProjectMembers(project.id)` call with a parallel fetch (keep the request-id guard):

```ts
      const [memberRows, quotaRow] = await Promise.all([
        listProjectMembers(project.id),
        getProjectStorageQuota(project.id),
      ])
      if (detailRequestRef.current !== requestId) {
        return
      }
      setMembers(memberRows)
      setStorageQuota(quotaRow)
      setQuotaInput(
        quotaRow.source === 'team' && quotaRow.quota_bytes !== null
          ? String(quotaRow.quota_bytes / 1024 ** 3)
          : '',
      )
```

New handler next to `onInvite`:

```ts
  async function onSaveQuota(event: React.FormEvent) {
    event.preventDefault()
    if (!selectedProject) {
      return
    }
    setBusy(true)
    setBanner(null)
    try {
      const trimmed = quotaInput.trim()
      const bytes =
        trimmed === '' ? null : Math.round(parseFloat(trimmed) * 1024 ** 3)
      const updated = await updateProjectStorageQuota(
        selectedProject.id,
        bytes,
      )
      setStorageQuota(updated)
      setBanner({ tone: 'ok', text: 'Storage quota updated.' })
    } catch (error) {
      setBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }
```

New section JSX — insert inside the `<>` after `detailLoading` resolves, BEFORE the Members `<section>`:

```tsx
                  <section className="teams-page__section">
                    <h3 className="teams-page__section-title">Storage</h3>
                    {storageQuota === null ? (
                      <p className="teams-page__muted">Loading storage…</p>
                    ) : storageQuota.quota_bytes === null ? (
                      <p className="teams-page__muted">
                        {formatGib(storageQuota.used_bytes)} used · No limit
                      </p>
                    ) : (
                      <>
                        <p className="teams-page__muted">
                          {formatGib(storageQuota.used_bytes)} of{' '}
                          {formatGib(storageQuota.quota_bytes)} used
                        </p>
                        <div className="teams-page__storage-bar">
                          <div
                            className={
                              storageQuota.over_quota
                                ? 'teams-page__storage-bar-fill teams-page__storage-bar-fill--over'
                                : 'teams-page__storage-bar-fill'
                            }
                            style={{
                              width: `${Math.min(
                                100,
                                (storageQuota.used_bytes /
                                  storageQuota.quota_bytes) *
                                  100,
                              )}%`,
                            }}
                          />
                        </div>
                        {storageQuota.over_quota ? (
                          <p className="teams-page__hint teams-page__hint--err">
                            Over quota — new deployments are blocked until
                            storage drops below the limit.
                          </p>
                        ) : null}
                      </>
                    )}
                    {isSelectedOwner ? (
                      <form
                        className="teams-page__quota-form"
                        onSubmit={onSaveQuota}
                      >
                        <label className="teams-page__field">
                          Limit (GB)
                          <input
                            type="number"
                            min="0"
                            step="0.1"
                            className="teams-page__input"
                            value={quotaInput}
                            disabled={busy}
                            onChange={(event) =>
                              setQuotaInput(event.target.value)
                            }
                            placeholder="Platform default"
                          />
                        </label>
                        <button
                          type="submit"
                          className="btn btn--primary"
                          disabled={busy}
                        >
                          Save
                        </button>
                      </form>
                    ) : null}
                  </section>
```

- [x] **Step 3: Add CSS**

In `frontend/src/index.css`, next to the existing `.teams-page__*` rules:

```css
.teams-page__storage-bar {
  height: 8px;
  border-radius: 4px;
  background: #e5e7eb;
  overflow: hidden;
}

.teams-page__storage-bar-fill {
  height: 100%;
  background: #4f46e5;
  transition: width 0.2s ease;
}

.teams-page__storage-bar-fill--over {
  background: #dc2626;
}

.teams-page__hint--err {
  color: #dc2626;
}

.teams-page__quota-form {
  display: flex;
  gap: 0.75rem;
  align-items: flex-end;
  margin-top: 1rem;
}
```

- [x] **Step 4: Build and lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: both succeed with no new errors.

- [x] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/pages/TeamsPage.tsx frontend/src/index.css
git commit -m "feat: show and edit team storage quota on the Teams page"
```

---

### Task 8: E2E — new `teams.spec.ts`

**Files:**
- Create: `frontend/e2e/teams.spec.ts`

**Interfaces:**
- Consumes: the `authenticatedPage` fixture (`frontend/e2e/fixtures.ts`); the Storage section from Task 7; the E2E backend does NOT set `VELA_TEAM_STORAGE_QUOTA_BYTES` (so the platform default is "unlimited").

- [x] **Step 1: Write the spec**

Create `frontend/e2e/teams.spec.ts`:

```ts
import { appBase } from './constants'
import { expect, test } from './fixtures'

const baseURL = appBase

test.describe('teams page', () => {
  test('shows the storage section with the platform default', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto(`${baseURL}/teams`)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Storage', level: 3 }),
    ).toBeVisible()
    await expect(authenticatedPage.getByText('No limit')).toBeVisible()
    // The signed-in user owns their personal team, so the editor is visible.
    await expect(
      authenticatedPage.getByRole('button', { name: 'Save' }),
    ).toBeVisible()
  })
})
```

- [x] **Step 2: Run the spec**

Ensure nothing else is using ports 8000/5173, then run: `cd frontend && npm run test:e2e -- e2e/teams.spec.ts`
Expected: PASS (1 test).

- [x] **Step 3: Commit**

```bash
git add frontend/e2e/teams.spec.ts
git commit -m "test: e2e coverage for the team storage section"
```

---

### Task 9: Docs + full verification

**Files:**
- Modify: `README.md` (env var table next to the `VELA_CONTAINER_MONITOR_INTERVAL_SECONDS` row, ~line 92)

- [x] **Step 1: Document the env var**

In `README.md`, add a row to the env var table:

```markdown
| `VELA_TEAM_STORAGE_QUOTA_BYTES` | Per-team storage quota in bytes (unset = unlimited; a team setting can only restrict it) |
```

- [x] **Step 2: Run the backend suite**

Run: `cd backend && python -m pytest -q`
Expected: full suite PASS.

- [x] **Step 3: Run the frontend gates**

Run: `cd frontend && npm run build && npm run lint`
Expected: PASS.

- [x] **Step 4: Run the full E2E suite**

Run: `cd frontend && npm run test:e2e`
Expected: all specs PASS.

- [x] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document VELA_TEAM_STORAGE_QUOTA_BYTES"
```

---

### Task 10: (Optional — only after the resource-dashboard plan is merged) Quota in the dashboard usage endpoint and panel

**Skip this entire task if `backend/app/api/routes/metrics.py` (created by `2025-08-03-resource-dashboard.md`) does not exist yet.** Re-run it once that plan lands; nothing in Tasks 1–9 depends on it.

**Files:**
- Modify: `backend/app/api/schemas.py` (`ProjectUsage` created by the dashboard plan)
- Modify: `backend/app/api/routes/metrics.py` (the `GET /api/metrics/usage` endpoint)
- Modify: `frontend/src/pages/containers/ResourceUsagePanel.tsx` (team rollup cards)
- Test: `backend/tests/test_storage_quota.py` (append)

**Interfaces:**
- Consumes: `usage_from_containers(session, containers, project_id)`, `effective_quota_bytes(project)` (Task 3); `ProjectUsage` schema and usage endpoint from the dashboard plan.
- Produces: `ProjectUsage` gains `storage_quota_bytes: int | null`, `storage_used_bytes: int`, `storage_over_quota: bool`; the dashboard usage panel shows per-team storage quota lines.

- [x] **Step 1: Extend `ProjectUsage`**

In `backend/app/api/schemas.py`, on the `ProjectUsage` schema created by the dashboard plan, add:

```python
    storage_quota_bytes: int | None = None
    storage_used_bytes: int = 0
    storage_over_quota: bool = False
```

- [x] **Step 2: Write the failing test**

Append to `backend/tests/test_storage_quota.py`:

```python
def test_usage_endpoint_includes_storage_fields(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    seeded_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_TEAM_STORAGE_QUOTA_BYTES", str(2 * _GB))
    fake_orchestrator.set_disk_bytes("cid-1", _GB)
    response = api_client.get("/api/metrics/usage")
    assert response.status_code == 200, response.text
    personal = next(
        project
        for project in response.json()["projects"]
        if project["id"] == str(seeded_user.personal_project_id)
    )
    assert personal["storage_quota_bytes"] == 2 * _GB
    assert personal["storage_used_bytes"] == _GB
    assert personal["storage_over_quota"] is False
```

- [x] **Step 3: Implement the endpoint fields**

In the usage endpoint in `backend/app/api/routes/metrics.py`, fetch `containers = await orchestrator.list()` once, then fill the three fields per project:

```python
    from app.core.quotas import effective_quota_bytes, usage_from_containers

    disk, uploads = await usage_from_containers(session, containers, project.id)
    used = disk + uploads
    quota = effective_quota_bytes(project)
```

and set `storage_quota_bytes=quota`, `storage_used_bytes=used`, `storage_over_quota=quota is not None and used >= quota` on each `ProjectUsage` row.

- [x] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_storage_quota.py -q`
Expected: PASS. Commit: `git add backend/app/api/schemas.py backend/app/api/routes/metrics.py backend/tests/test_storage_quota.py && git commit -m "feat: include storage quota in the usage endpoint"`

- [x] **Step 5: Dashboard panel quota line**

In `frontend/src/pages/containers/ResourceUsagePanel.tsx` (created by the dashboard plan), on each team rollup card, render below the usage numbers (reuse the same `formatGib` shape as TeamsPage; if the file has no helper, add the two-line `formatGib`):

```tsx
{project.storage_quota_bytes !== null ? (
  <p className="resource-usage__quota">
    {formatGib(project.storage_used_bytes)} of{' '}
    {formatGib(project.storage_quota_bytes)}
    {project.storage_over_quota ? ' (over quota)' : ''}
  </p>
) : (
  <p className="resource-usage__quota">{formatGib(project.storage_used_bytes)} used</p>
)}
```

Add a `.resource-usage__quota` CSS rule if the panel's class block does not define one.

- [x] **Step 6: Build + lint + commit**

Run: `cd frontend && npm run build && npm run lint`
Expected: PASS.

```bash
git add frontend/src/pages/containers/ResourceUsagePanel.tsx frontend/src/index.css
git commit -m "feat: show team storage quota in the usage panel"
```

---

## Self-Review

**Spec coverage:** quota unit = team (project) with personal-team inheritance — Tasks 1, 3; env default + restrict-only override — Tasks 1, 3, 5; hard block on run/deploy — Task 4; upload block — Task 4; settings endpoints — Task 5; Teams-page visibility + owner edit — Task 7; rising-edge email alert, no auto-stop, no recovery alert — Task 3 (state) + Task 6 (dispatch + hook); boundaries (writable layer only, image pulls uncounted, state resets on restart) — documented in Global Constraints and `check_team_storage_quotas` docstring; E2E — Task 8; full verification — Task 9; dashboard integration — Task 10 (gated on the dashboard plan).

**Type consistency:** `TeamStorageQuotaSummary` field names match `ProjectStorageQuotaPublic` (quota_bytes/used_bytes/container_disk_bytes/uploads_bytes/over_quota/source); `storage_quota_bytes` column name is identical on the ORM model, `ProjectPublic`, and the frontend `Project` type; `usage_from_containers` is public in `app.core.quotas` (Task 3 `__init__`) and reused by Tasks 4/10; `_GB` helper and `_make_info` are shared across appended test sections.

**Known boundaries (accepted in design):** container disk counts the writable layer only (named/anonymous volumes untracked); image pulls uncounted (shared layer); per-member upload scan is O(team size) per check; quota state resets on API restart (re-alarms once if still over).

## Status (2026-09-02)

Fully implemented and verified on `f/resource-management` (pytest + E2E green at 2026-09-02 review).
