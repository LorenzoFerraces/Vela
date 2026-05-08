"""Persist GitHub OAuth identities (encrypted token + display profile)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.oauth.github import GitHubProfile
from app.core.security.secrets import decrypt_secret, encrypt_secret
from app.db.models import UserOAuthIdentity

GITHUB_PROVIDER = "github"


async def get_github_identity(
    session: AsyncSession, user_id: uuid.UUID
) -> UserOAuthIdentity | None:
    """Return the user's GitHub identity row, if any."""
    return await session.scalar(
        select(UserOAuthIdentity).where(
            UserOAuthIdentity.user_id == user_id,
            UserOAuthIdentity.provider == GITHUB_PROVIDER,
        )
    )


async def upsert_github_identity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    profile: GitHubProfile,
    access_token: str,
    scopes: str,
) -> UserOAuthIdentity:
    """Insert or update the user's GitHub identity. Commits before returning."""
    identity = await get_github_identity(session, user_id)
    encrypted = encrypt_secret(access_token)
    now = datetime.now(timezone.utc)

    if identity is None:
        identity = UserOAuthIdentity(
            user_id=user_id,
            provider=GITHUB_PROVIDER,
            provider_subject=str(profile.id),
            username=profile.login,
            avatar_url=profile.avatar_url,
            scopes=scopes,
            access_token_encrypted=encrypted,
            connected_at=now,
            updated_at=now,
        )
        session.add(identity)
    else:
        identity.provider_subject = str(profile.id)
        identity.username = profile.login
        identity.avatar_url = profile.avatar_url
        identity.scopes = scopes
        identity.access_token_encrypted = encrypted
        identity.updated_at = now

    await session.commit()
    await session.refresh(identity)
    return identity


async def delete_github_identity(
    session: AsyncSession, user_id: uuid.UUID
) -> UserOAuthIdentity | None:
    """Delete the user's GitHub identity (if present) and return the deleted row."""
    identity = await get_github_identity(session, user_id)
    if identity is None:
        return None
    await session.delete(identity)
    await session.commit()
    return identity


def decrypt_identity_token(identity: UserOAuthIdentity) -> str | None:
    """Decrypt the stored access token; ``None`` when the row predates token storage."""
    if identity.access_token_encrypted is None:
        return None
    return decrypt_secret(identity.access_token_encrypted)
