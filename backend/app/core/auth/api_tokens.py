"""Personal access tokens used by the Vela CLI."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiToken, User

API_TOKEN_PREFIX = "vela_pat_"
PREFIX_LENGTH = 16


@dataclass(frozen=True)
class MintedApiToken:
    plaintext: str
    prefix: str
    token_hash: str


def hash_api_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def mint_api_token() -> MintedApiToken:
    plaintext = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return MintedApiToken(
        plaintext=plaintext,
        prefix=plaintext[:PREFIX_LENGTH],
        token_hash=hash_api_token(plaintext),
    )


async def create_api_token(
    session: AsyncSession, user_id: uuid.UUID, name: str
) -> tuple[ApiToken, MintedApiToken]:
    minted = mint_api_token()
    record = ApiToken(
        user_id=user_id,
        name=name,
        token_prefix=minted.prefix,
        token_hash=minted.token_hash,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record, minted


async def get_user_by_api_token(
    session: AsyncSession, plaintext: str
) -> User | None:
    result = await session.execute(
        select(User)
        .join(ApiToken, ApiToken.user_id == User.id)
        .where(ApiToken.token_hash == hash_api_token(plaintext))
    )
    return result.scalar_one_or_none()
