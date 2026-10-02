import asyncio
from typing import Any

import pytest


def test_ensure_admin_user_preserves_existing_account_state(
    db_session_factory: Any, monkeypatch: Any
) -> None:
    from app.core.auth.bootstrap import ensure_admin_user

    monkeypatch.setenv("VELA_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("VELA_ADMIN_PASSWORD", "admin-password-min-8")

    async def run_create() -> str:
        async with db_session_factory() as session:
            user = await ensure_admin_user(session)
            assert user is not None
            assert user.role == "admin"
            assert user.is_active is True
            return user.email

    assert asyncio.run(run_create()) == "root@example.com"

    async def run_deactivate_then_ensure() -> None:
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
    from app.core.auth.bootstrap import ensure_admin_user

    monkeypatch.setenv("VELA_ADMIN_EMAIL", "root@example.com")
    monkeypatch.setenv("VELA_ADMIN_PASSWORD", "short")

    async def run() -> None:
        async with db_session_factory() as session:
            with pytest.raises(ValueError, match="8 and 128"):
                await ensure_admin_user(session)

    asyncio.run(run())


def test_ensure_admin_user_noop_without_env(db_session_factory: Any, monkeypatch: Any) -> None:
    from app.core.auth.bootstrap import ensure_admin_user

    monkeypatch.delenv("VELA_ADMIN_EMAIL", raising=False)

    async def run() -> None:
        async with db_session_factory() as session:
            assert await ensure_admin_user(session) is None

    asyncio.run(run())
