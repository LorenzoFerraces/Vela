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

from app.core.containers.docker_orchestrator import _inspect_to_container_info
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
