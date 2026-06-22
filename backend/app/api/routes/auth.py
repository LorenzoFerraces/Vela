"""Email + password authentication routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_object_storage
from app.api.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)
from app.api.user_view import user_public_from_snapshot
from app.core.auth.service import authenticate, register_user
from app.core.auth.tokens import create_access_token
from app.core.profile.service import user_to_snapshot
from app.core.storage.object_storage import ObjectStorage
from app.db.models import User

router = APIRouter()


def _token_response(user: User, object_storage: ObjectStorage) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=user_public_from_snapshot(user_to_snapshot(user, object_storage)),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> TokenResponse:
    """Create an account and return an access token for the new user."""
    user = await register_user(session, email=body.email, password=body.password)
    return _token_response(user, object_storage)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> TokenResponse:
    """Verify credentials and return an access token."""
    user = await authenticate(session, email=body.email, password=body.password)
    return _token_response(user, object_storage)


@router.get("/me", response_model=UserPublic)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> UserPublic:
    """Return the user identified by the bearer token."""
    return user_public_from_snapshot(user_to_snapshot(current_user, object_storage))
