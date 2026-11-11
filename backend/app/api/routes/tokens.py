"""Personal access token routes for the Vela CLI."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_jwt_authenticated_user
from app.api.schemas import ApiTokenCreate, ApiTokenCreated, ApiTokenPublic
from app.core.auth.api_tokens import create_api_token
from app.core.exceptions import ApiTokenNotFoundError
from app.db.models import ApiToken, User

router = APIRouter()


@router.post("/", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: ApiTokenCreate,
    user: Annotated[User, Depends(get_jwt_authenticated_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ApiTokenCreated:
    """Create a token from an interactive JWT login; PATs cannot mint tokens."""
    record, minted = await create_api_token(session, user.id, body.name)
    return ApiTokenCreated(
        id=record.id,
        name=record.name,
        prefix=record.token_prefix,
        created_at=record.created_at,
        token=minted.plaintext,
    )


@router.get("/", response_model=list[ApiTokenPublic])
async def list_tokens(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ApiTokenPublic]:
    """List the caller's tokens without secrets, newest first."""
    result = await session.execute(
        select(ApiToken)
        .where(ApiToken.user_id == user.id)
        .order_by(ApiToken.created_at.desc())
    )
    return [
        ApiTokenPublic(
            id=record.id,
            name=record.name,
            prefix=record.token_prefix,
            created_at=record.created_at,
        )
        for record in result.scalars()
    ]


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Revoke one of the caller's tokens by id."""
    result = await session.execute(
        select(ApiToken).where(
            ApiToken.id == token_id, ApiToken.user_id == user.id
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise ApiTokenNotFoundError("API token not found.")
    await session.delete(record)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
