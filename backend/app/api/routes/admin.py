"""Admin user management API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, require_instructor
from app.api.schemas import (
    AdminUserCreate,
    AdminUserListResponse,
    AdminUserPatch,
    AdminUserPublic,
)
from app.core.admin import service as admin_service
from app.core.auth.enums import UserRole
from app.db.models import User

router = APIRouter()


def _to_public(user: User) -> AdminUserPublic:
    return AdminUserPublic(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=UserRole(user.role),
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    query: Annotated[str | None, Query(max_length=200)] = None,
    role: Annotated[UserRole | None, Query()] = None,
    status_filter: Annotated[bool | None, Query(alias="is_active")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminUserListResponse:
    users, total = await admin_service.list_users(
        session,
        query=query,
        role=role,
        is_active=status_filter,
        limit=limit,
        offset=offset,
    )
    return AdminUserListResponse(users=[_to_public(user) for user in users], total=total)


@router.post(
    "/users",
    response_model=AdminUserPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    body: AdminUserCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(require_instructor)],
) -> AdminUserPublic:
    user = await admin_service.create_user(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        role=body.role,
        actor=actor,
    )
    return _to_public(user)


@router.patch("/users/{user_id}", response_model=AdminUserPublic)
async def patch_user(
    user_id: uuid.UUID,
    body: AdminUserPatch,
    session: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(require_admin)],
) -> AdminUserPublic:
    try:
        user = await admin_service.update_user(
            session,
            user_id=user_id,
            role=body.role,
            is_active=body.is_active,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc
    return _to_public(user)
