"""High-level authentication operations."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.passwords import verify_password
from app.core.exceptions import AccountDeactivatedError, InvalidCredentialsError
from app.db.models import User


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    """Look up the user and verify the password; raise on any mismatch."""
    normalized_email = _normalize_email(email)
    user = await session.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        raise InvalidCredentialsError()
    if user.password_hash is None:
        raise InvalidCredentialsError()
    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()
    if not user.is_active:
        raise AccountDeactivatedError()
    return user


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)
