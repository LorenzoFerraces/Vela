"""Authenticated user profile routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_object_storage
from app.api.schemas import UserProfileUpdate, UserPublic
from app.api.user_view import user_public_from_snapshot
from app.core.profile.service import delete_avatar, update_profile, upload_avatar
from app.core.storage.object_storage import ObjectStorage
from app.db.models import User

router = APIRouter()


@router.patch("/me", response_model=UserPublic)
async def patch_me(
    body: UserProfileUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> UserPublic:
    """Update display name and pronouns for the current user."""
    updates = body.model_dump(exclude_unset=True)
    snapshot = await update_profile(
        session,
        current_user,
        display_name=updates.get("display_name", ...),
        pronouns=updates.get("pronouns", ...),
        object_storage=object_storage,
    )
    return user_public_from_snapshot(snapshot)


@router.post("/me/avatar", response_model=UserPublic)
async def post_avatar(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    file: UploadFile = File(...),
) -> UserPublic:
    """Upload or replace the current user's avatar."""
    body = await file.read()
    snapshot = await upload_avatar(
        session,
        current_user,
        body=body,
        object_storage=object_storage,
    )
    return user_public_from_snapshot(snapshot)


@router.delete("/me/avatar", response_model=UserPublic)
async def remove_avatar(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> UserPublic:
    """Remove the current user's avatar."""
    snapshot = await delete_avatar(
        session,
        current_user,
        object_storage=object_storage,
    )
    return user_public_from_snapshot(snapshot)
