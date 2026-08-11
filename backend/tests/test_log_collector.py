import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging.collector import batch_insert_logs, cleanup_old_logs
from app.db.models import ContainerLog, LogLevel, LogSource
from sqlalchemy import select


def test_batch_insert_logs(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        logs = [
            ContainerLog(
                container_id="cid-1",
                container_name="test",
                timestamp=datetime.now(timezone.utc),
                source=LogSource.STDOUT,
                level=LogLevel.INFO,
                message="hello",
            ),
            ContainerLog(
                container_id="cid-2",
                container_name="test2",
                timestamp=datetime.now(timezone.utc),
                source=LogSource.STDERR,
                level=LogLevel.ERROR,
                message="fail",
            ),
        ]
        async with db_session_factory() as session:
            await batch_insert_logs(session, logs)
            result = await session.execute(
                select(ContainerLog)
            )
            rows = result.scalars().all()
            assert len(rows) == 2

    asyncio.run(run())


def test_batch_insert_logs_empty(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        async with db_session_factory() as session:
            await batch_insert_logs(session, [])
            result = await session.execute(
                select(ContainerLog)
            )
            rows = result.scalars().all()
            assert len(rows) == 0

    asyncio.run(run())


def test_cleanup_old_logs(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        now = datetime.now(timezone.utc)
        old_logs = [
            ContainerLog(
                container_id="cid-1",
                container_name="old",
                timestamp=now - timedelta(days=10),
                created_at=now - timedelta(days=10),
                source=LogSource.STDOUT,
                level=LogLevel.INFO,
                message="old log",
            ),
            ContainerLog(
                container_id="cid-1",
                container_name="old",
                timestamp=now - timedelta(days=8),
                created_at=now - timedelta(days=8),
                source=LogSource.STDOUT,
                level=LogLevel.WARN,
                message="also old",
            ),
        ]
        recent_logs = [
            ContainerLog(
                container_id="cid-2",
                container_name="recent",
                timestamp=now - timedelta(hours=1),
                created_at=now - timedelta(hours=1),
                source=LogSource.STDOUT,
                level=LogLevel.INFO,
                message="recent log",
            ),
        ]
        async with db_session_factory() as session:
            await batch_insert_logs(session, old_logs + recent_logs)

        async with db_session_factory() as session:
            deleted = await cleanup_old_logs(session, retention_days=7)
            assert deleted == 2

        async with db_session_factory() as session:
            result = await session.execute(
                select(ContainerLog)
            )
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].message == "recent log"

    asyncio.run(run())
