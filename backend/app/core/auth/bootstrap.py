"""Ensure the env-configured bootstrap admin exists at startup."""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.enums import UserRole
from app.core.auth.passwords import hash_password
from app.core.projects.bootstrap import ensure_personal_workspace
from app.db.models import User


async def ensure_admin_user(session: AsyncSession) -> User | None:
    email = os.environ.get("VELA_ADMIN_EMAIL", "").strip().lower()
    if not email:
        return None

    password = os.environ.get("VELA_ADMIN_PASSWORD", "")
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        if not password:
            raise ValueError("VELA_ADMIN_PASSWORD is required when creating VELA_ADMIN_EMAIL")
        user = User(email=email, password_hash=hash_password(password))
        session.add(user)
        await session.flush()
        await ensure_personal_workspace(session, user)
    user.role = UserRole.ADMIN.value
    user.is_active = True
    await session.commit()
    await session.refresh(user)
    return user
