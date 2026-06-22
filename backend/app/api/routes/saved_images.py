"""CRUD for per-user saved Docker image references (PostgreSQL)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import SavedImageCreate, SavedImagePublic, SavedImageUpdate
from app.core import user_library
from app.db.models import User

router = APIRouter()


@router.get("/", response_model=list[SavedImagePublic])
async def list_saved_images(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[SavedImagePublic]:
    """List the caller's saved image references."""
    rows = await user_library.list_saved_images(session, current_user.id)
    return [SavedImagePublic.model_validate(row) for row in rows]


@router.post(
    "/",
    response_model=SavedImagePublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_saved_image(
    body: SavedImageCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SavedImagePublic:
    """Save a Docker image reference for later use."""
    try:
        row = await user_library.create_saved_image(
            session, current_user.id, body.ref
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return SavedImagePublic.model_validate(row)


@router.get("/{image_id}", response_model=SavedImagePublic)
async def get_saved_image(
    image_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SavedImagePublic:
    """Return one saved image reference owned by the caller."""
    row = await user_library.get_saved_image(session, current_user.id, image_id)
    return SavedImagePublic.model_validate(row)


@router.patch("/{image_id}", response_model=SavedImagePublic)
async def update_saved_image(
    image_id: uuid.UUID,
    body: SavedImageUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SavedImagePublic:
    """Update a saved image reference."""
    try:
        row = await user_library.update_saved_image(
            session, current_user.id, image_id, ref=body.ref
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return SavedImagePublic.model_validate(row)


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_image(
    image_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Remove a saved image reference."""
    await user_library.delete_saved_image(session, current_user.id, image_id)
