"""Admin user management operations."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.enums import UserRole
from app.core.auth.passwords import hash_password
from app.core.exceptions import EmailAlreadyRegisteredError, PermissionDeniedError
from app.core.projects.bootstrap import ensure_personal_workspace
from app.db.models import User


async def list_users(
    session: AsyncSession,
    *,
    query: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    conditions = []
    if query:
        pattern = f"%{query.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(User.email).like(pattern),
                func.lower(User.display_name).like(pattern),
            )
        )
    if role is not None:
        conditions.append(User.role == role.value)
    if is_active is not None:
        conditions.append(User.is_active.is_(is_active))

    base = select(User)
    if conditions:
        base = base.where(*conditions)

    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    users = (
        await session.execute(
            base.order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(users), int(total)


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None,
    role: UserRole,
    actor: User,
) -> User:
    if role == UserRole.ADMIN and actor.role != UserRole.ADMIN:
        raise PermissionDeniedError("Only admins can create admin accounts.")

    normalized_email = email.strip().lower()
    existing = await session.scalar(
        select(User).where(User.email == normalized_email)
    )
    if existing is not None:
        raise EmailAlreadyRegisteredError(normalized_email)

    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role.value,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    await ensure_personal_workspace(session, user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    role: UserRole | None,
    is_active: bool | None,
    actor: User,
) -> User:
    if actor.role != UserRole.ADMIN:
        raise PermissionDeniedError("Admin access required.")

    user = await session.get(User, user_id)
    if user is None:
        raise LookupError("User not found")
    if role is not None:
        user.role = role.value
    if is_active is not None:
        user.is_active = is_active
    await session.commit()
    await session.refresh(user)
    return user
