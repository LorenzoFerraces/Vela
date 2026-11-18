import asyncio
from typing import Any

import pytest


def test_ensure_admin_user_preserves_existing_account_state(
    db_session_factory: Any, monkeypatch: Any
) -> None:
    """ensure_admin_user creates an active admin and later keeps existing account state."""
    from app.core.auth.bootstrap import ensure_admin_user

    monkeypatch.setenv("VELA_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("VELA_ADMIN_PASSWORD", "admin-password-min-8")

    async def run_create() -> str:
        """Create the admin user and return its email."""
        async with db_session_factory() as session:
            user = await ensure_admin_user(session)
            assert user is not None
            assert user.role == "admin"
            assert user.is_active is True
            return user.email

    assert asyncio.run(run_create()) == "root@example.com"

    async def run_deactivate_then_ensure() -> None:
        """Deactivate the admin, then check ensure_admin_user preserves that state."""
        async with db_session_factory() as session:
            from sqlalchemy import select
            from app.db.models import User

            user = await session.scalar(select(User).where(User.email == "root@example.com"))
            assert user is not None
            user.is_active = False
            user.role = "student"
            await session.commit()
            monkeypatch.delenv("VELA_ADMIN_PASSWORD")
            ensured = await ensure_admin_user(session)
            assert ensured is not None
            assert ensured.is_active is False
            assert ensured.role == "student"

    asyncio.run(run_deactivate_then_ensure())


def test_ensure_admin_user_rejects_short_password(
    db_session_factory: Any, monkeypatch: Any
) -> None:
    """ensure_admin_user raises ValueError when the admin password is too short."""
    from app.core.auth.bootstrap import ensure_admin_user

    monkeypatch.setenv("VELA_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("VELA_ADMIN_PASSWORD", "short")

    async def run() -> None:
        """Run ensure_admin_user and expect the short-password error."""
        async with db_session_factory() as session:
            with pytest.raises(ValueError, match="8 and 128"):
                await ensure_admin_user(session)

    asyncio.run(run())


def test_ensure_admin_user_noop_without_env(db_session_factory: Any, monkeypatch: Any) -> None:
    """ensure_admin_user returns None when no admin email is configured."""
    from app.core.auth.bootstrap import ensure_admin_user

    monkeypatch.delenv("VELA_ADMIN_EMAIL", raising=False)

    async def run() -> None:
        """Run ensure_admin_user and expect no user created."""
        async with db_session_factory() as session:
            assert await ensure_admin_user(session) is None

    asyncio.run(run())
