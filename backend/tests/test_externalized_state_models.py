"""Round-trip tests for the externalized-state ORM models (F04)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import DeployJobRecord, TrafficRouteRecord, WsTicketRecord


@pytest.fixture
async def quota_db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, future=True
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_deploy_job_record_round_trip(quota_db: AsyncSession) -> None:
    record = DeployJobRecord(
        job_id="abc123", kind="container", project_id=uuid.uuid4(), user_id=uuid.uuid4(),
        name="web", status="in_progress", phase="queued", services=[{"name": "web", "state": "pending"}],
    )
    quota_db.add(record)
    await quota_db.commit()
    loaded = (await quota_db.execute(select(DeployJobRecord))).scalar_one()
    assert loaded.job_id == "abc123"
    assert loaded.services == [{"name": "web", "state": "pending"}]


@pytest.mark.asyncio
async def test_traffic_route_and_ws_ticket_records(quota_db: AsyncSession) -> None:
    quota_db.add(TrafficRouteRecord(
        route_id="web-route", host="web.example", path_prefix="/", backend_servers=[{"host": "web", "port": 80}],
        tls_enabled=False, entrypoints=["web"],
    ))
    quota_db.add(WsTicketRecord(ticket="ticket-1", container_id="c1", purpose="logs"))
    await quota_db.commit()
    assert len((await quota_db.execute(select(TrafficRouteRecord))).scalars().all()) == 1
    assert len((await quota_db.execute(select(WsTicketRecord))).scalars().all()) == 1
