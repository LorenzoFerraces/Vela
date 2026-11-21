"""Personal access tokens used by the Vela CLI."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
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
    session: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    *,
    expires_at: datetime | None = None,
    scope: str = "full",
) -> tuple[ApiToken, MintedApiToken]:
    minted = mint_api_token()
    record = ApiToken(
        user_id=user_id,
        name=name,
        token_prefix=minted.prefix,
        token_hash=minted.token_hash,
        expires_at=expires_at,
        scope=scope,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record, minted


async def get_api_token_principal(
    session: AsyncSession, plaintext: str
) -> tuple[User, str] | None:
    """Resolve a live PAT to its owner and scope, recording last use."""
    now = datetime.now(UTC)
    result = await session.execute(
        select(User, ApiToken.id, ApiToken.scope)
        .join(ApiToken, ApiToken.user_id == User.id)
        .where(
            ApiToken.token_hash == hash_api_token(plaintext),
            (ApiToken.expires_at.is_(None)) | (ApiToken.expires_at > now),
        )
    )
    row = result.one_or_none()
    if row is None:
        return None
    user, token_id, scope = row
    await session.execute(
        update(ApiToken).where(ApiToken.id == token_id).values(last_used_at=now)
    )
    await session.commit()
    return user, scope


async def get_user_by_api_token(
    session: AsyncSession, plaintext: str
) -> User | None:
    principal = await get_api_token_principal(session, plaintext)
    return principal[0] if principal is not None else None
