"""Tests for email alerting (AlertService and preference defaults)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.notifications.alert_service import AlertService
from app.core.notifications.email_provider import ConsoleProvider
from app.db.base import Base
from app.db.models import AlertHistory, EmailPreference, User


@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite database for alert service tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_email_preference_creation(test_db: AsyncSession) -> None:
    user_id = uuid.uuid4()

    pref = EmailPreference(
        user_id=user_id,
        email="test@example.com",
        alerts_enabled=True,
        alert_types=["stop", "failure"],
        alert_frequency="immediate",
    )
    test_db.add(pref)
    await test_db.commit()

    await test_db.refresh(pref)
    assert pref.email == "test@example.com"
    assert pref.alerts_enabled is True
    assert "stop" in pref.alert_types


@pytest.mark.asyncio
async def test_alert_deduplication(test_db: AsyncSession) -> None:
    user_id = uuid.uuid4()
    container_id = "abc123"

    pref = EmailPreference(
        user_id=user_id,
        email="test@example.com",
        alerts_enabled=True,
        alert_types=["stop"],
        alert_frequency="immediate",
    )
    test_db.add(pref)
    await test_db.commit()

    provider = ConsoleProvider()
    alert_service = AlertService(provider, test_db)

    result1 = await alert_service.send_container_alert(
        user_id=user_id,
        container_id=container_id,
        container_name="my-app",
        event_type="stop",
        details="Container stopped",
    )
    assert result1 is True

    result2 = await alert_service.send_container_alert(
        user_id=user_id,
        container_id=container_id,
        container_name="my-app",
        event_type="stop",
        details="Container stopped again",
    )
    assert result2 is False

    entries = await alert_service.get_recent_alerts(user_id, container_id)
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_alert_respects_preferences(test_db: AsyncSession) -> None:
    user_id = uuid.uuid4()
    container_id = "xyz789"

    pref = EmailPreference(
        user_id=user_id,
        email="test@example.com",
        alerts_enabled=False,
        alert_types=["stop"],
        alert_frequency="immediate",
    )
    test_db.add(pref)
    await test_db.commit()

    provider = ConsoleProvider()
    alert_service = AlertService(provider, test_db)

    result = await alert_service.send_container_alert(
        user_id=user_id,
        container_id=container_id,
        container_name="my-app",
        event_type="stop",
    )
    assert result is False


@pytest.mark.asyncio
async def test_alert_type_filtering(test_db: AsyncSession) -> None:
    user_id = uuid.uuid4()
    container_id = "def456"

    pref = EmailPreference(
        user_id=user_id,
        email="test@example.com",
        alerts_enabled=True,
        alert_types=["stop"],
        alert_frequency="immediate",
    )
    test_db.add(pref)
    await test_db.commit()

    provider = ConsoleProvider()
    alert_service = AlertService(provider, test_db)

    result1 = await alert_service.send_container_alert(
        user_id=user_id,
        container_id=container_id,
        container_name="my-app",
        event_type="stop",
    )
    assert result1 is True

    result2 = await alert_service.send_container_alert(
        user_id=user_id,
        container_id=container_id,
        container_name="my-app",
        event_type="failure",
    )
    assert result2 is False

    entries = await alert_service.get_recent_alerts(user_id, container_id)
    assert len(entries) == 1
    assert entries[0].event_type == "stop"


@pytest.mark.asyncio
async def test_alert_uses_defaults_without_saved_preferences(test_db: AsyncSession) -> None:
    user_id = uuid.uuid4()
    user = User(id=user_id, email="owner@example.com", password_hash=None)
    test_db.add(user)
    await test_db.commit()

    provider = ConsoleProvider()
    alert_service = AlertService(provider, test_db)

    result = await alert_service.send_container_alert(
        user_id=user_id,
        container_id="container-1",
        container_name="my-app",
        event_type="stop",
    )
    assert result is True

    entries = await alert_service.get_recent_alerts(user_id)
    assert len(entries) == 1
    assert entries[0].email_sent_to == "owner@example.com"


@pytest.mark.asyncio
async def test_non_immediate_frequency_skips_send(test_db: AsyncSession) -> None:
    user_id = uuid.uuid4()

    pref = EmailPreference(
        user_id=user_id,
        email="test@example.com",
        alerts_enabled=True,
        alert_types=["stop"],
        alert_frequency="daily_digest",
    )
    test_db.add(pref)
    await test_db.commit()

    provider = ConsoleProvider()
    alert_service = AlertService(provider, test_db)

    result = await alert_service.send_container_alert(
        user_id=user_id,
        container_id="container-1",
        container_name="my-app",
        event_type="stop",
    )
    assert result is False

    entries = await alert_service.get_recent_alerts(user_id)
    assert entries == []
