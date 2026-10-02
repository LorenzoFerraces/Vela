"""Create the env-configured bootstrap admin when it is missing."""

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

    user = await session.scalar(select(User).where(User.email == email))
    if user is not None:
        return user

    password = os.environ.get("VELA_ADMIN_PASSWORD", "")
    if not password:
        raise ValueError("VELA_ADMIN_PASSWORD is required when creating VELA_ADMIN_EMAIL")
    if not 8 <= len(password) <= 128:
        raise ValueError("VELA_ADMIN_PASSWORD must be between 8 and 128 characters")
    user = User(
        email=email,
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    await ensure_personal_workspace(session, user)
    await session.commit()
    await session.refresh(user)
    return user
