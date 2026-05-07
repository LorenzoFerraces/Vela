"""Email + password authentication routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)
from app.core.auth.service import authenticate, register_user
from app.core.auth.tokens import create_access_token
from app.db.models import User

router = APIRouter()


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserPublic.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Create an account and return an access token for the new user."""
    user = await register_user(session, email=body.email, password=body.password)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Verify credentials and return an access token."""
    user = await authenticate(session, email=body.email, password=body.password)
    return _token_response(user)


@router.get("/me", response_model=UserPublic)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserPublic:
    """Return the user identified by the bearer token."""
    return UserPublic.model_validate(current_user)
