"""Audit service unit tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit.service import emit_audit_log, list_audit_logs
from app.db.models import AuditLog


@pytest.fixture
def user_a() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def user_b() -> uuid.UUID:
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


async def _emit(
    factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: str,
    details: dict | None = None,
) -> None:
    async with factory() as session:
        await emit_audit_log(session, user_id, action, target_type, target_id, details)
        await session.commit()


async def _query(
    factory: async_sessionmaker[AsyncSession],
    **kwargs,
) -> list[AuditLog]:
    async with factory() as session:
        result = await list_audit_logs(session, **kwargs)
        return result.entries


def test_emit_and_list_basic(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    async def run() -> None:
        await _emit(
            db_session_factory,
            user_id=user_a,
            action="container.deploy",
            target_type="container",
            target_id="cid-1",
            details={"image": "nginx:alpine"},
        )
        entries = await _query(db_session_factory)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.user_id == user_a
        assert entry.action == "container.deploy"
        assert entry.target_type == "container"
        assert entry.target_id == "cid-1"
        assert entry.details == {"image": "nginx:alpine"}
        assert entry.created_at is not None

    asyncio.run(run())


def test_list_filters_by_user(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    async def run() -> None:
        await _emit(
            db_session_factory, user_a, "container.start", "container", "cid-1"
        )
        await _emit(
            db_session_factory, user_b, "container.stop", "container", "cid-2"
        )
        await _emit(
            db_session_factory, user_a, "user.profile_update", "user", str(user_a)
        )

        user_a_entries = await _query(db_session_factory, user_id=user_a)
        assert len(user_a_entries) == 2
        assert all(e.user_id == user_a for e in user_a_entries)

        user_b_entries = await _query(db_session_factory, user_id=user_b)
        assert len(user_b_entries) == 1
        assert user_b_entries[0].action == "container.stop"

    asyncio.run(run())


def test_list_filters_by_action(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    async def run() -> None:
        await _emit(
            db_session_factory, user_a, "container.deploy", "container", "cid-1"
        )
        await _emit(
            db_session_factory, user_a, "container.start", "container", "cid-1"
        )
        await _emit(
            db_session_factory, user_a, "container.deploy", "container", "cid-2"
        )

        deploys = await _query(db_session_factory, action="container.deploy")
        assert len(deploys) == 2

        starts = await _query(db_session_factory, action="container.start")
        assert len(starts) == 1

    asyncio.run(run())


def test_list_filters_by_target_type(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    async def run() -> None:
        await _emit(
            db_session_factory, user_a, "container.deploy", "container", "cid-1"
        )
        await _emit(
            db_session_factory, user_a, "user.profile_update", "user", str(user_a)
        )

        containers = await _query(db_session_factory, target_type="container")
        assert len(containers) == 1
        assert containers[0].target_type == "container"

        users = await _query(db_session_factory, target_type="user")
        assert len(users) == 1
        assert users[0].target_type == "user"

    asyncio.run(run())


def test_list_orders_newest_first(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    async def run() -> None:
        await _emit(
            db_session_factory, user_a, "container.deploy", "container", "cid-1"
        )
        await asyncio.sleep(0.01)
        await _emit(
            db_session_factory, user_a, "container.start", "container", "cid-1"
        )

        entries = await _query(db_session_factory)
        assert len(entries) == 2
        assert entries[0].action == "container.start"
        assert entries[1].action == "container.deploy"

    asyncio.run(run())


def test_list_limit_and_offset(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    async def run() -> None:
        for i in range(5):
            await _emit(
                db_session_factory,
                user_a,
                f"container.action{i}",
                "container",
                f"cid-{i}",
            )

        page1 = await _query(db_session_factory, limit=2, offset=0)
        assert len(page1) == 2

        page2 = await _query(db_session_factory, limit=2, offset=2)
        assert len(page2) == 2

        page3 = await _query(db_session_factory, limit=2, offset=4)
        assert len(page3) == 1

    asyncio.run(run())


def test_list_date_range_filter(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    async def run() -> None:
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        await _emit(
            db_session_factory, user_a, "container.deploy", "container", "cid-1"
        )

        future_entries = await _query(
            db_session_factory, from_date=tomorrow
        )
        assert len(future_entries) == 0

        past_entries = await _query(
            db_session_factory, from_date=yesterday, to_date=tomorrow
        )
        assert len(past_entries) == 1

    asyncio.run(run())


def test_emit_with_none_details(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    async def run() -> None:
        await _emit(
            db_session_factory,
            user_id=user_a,
            action="container.stop",
            target_type="container",
            target_id="cid-1",
            details=None,
        )
        entries = await _query(db_session_factory)
        assert len(entries) == 1
        assert entries[0].details is None

    asyncio.run(run())


def test_emit_persists_without_explicit_commit(
    db_session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """emit_audit_log commits internally; entry must survive a fresh session."""
    async def run() -> None:
        async with db_session_factory() as session:
            await emit_audit_log(
                session,
                user_id=user_a,
                action="container.deploy",
                target_type="container",
                target_id="cid-persist",
            )

        entries = await _query(db_session_factory)
        assert len(entries) == 1
        assert entries[0].action == "container.deploy"

    asyncio.run(run())
