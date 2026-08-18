"""Tests for team (project) storage quota."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.containers.docker_orchestrator import (
    VELA_MANAGED_LABEL,
    VELA_OWNER_LABEL,
    VELA_PROJECT_LABEL,
    _inspect_to_container_info,
)
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus, HealthStatus
from app.core.exceptions import TeamStorageQuotaExceededError
from app.core.models import ContainerInfo
from app.core.quotas import storage_quota
from app.db.base import Base
from app.db.models import (
    AlertHistory,
    EmailPreference,
    Organization,
    Project,
    ProjectMembership,
    User,
)


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


@pytest.fixture(autouse=True)
def _reset_over_quota_state() -> None:
    storage_quota.reset_over_quota_state()


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
