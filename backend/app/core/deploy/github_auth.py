"""GitHub HTTPS auth helpers for git-source deploys (token lookup, failure heuristics)."""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.oauth import decrypt_identity_token, get_github_identity
from app.db.models import User


def is_github_https_url(source: str) -> bool:
    """True for the HTTPS forms we can authenticate with a stored access token."""
    try:
        parsed = urlparse(source)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host == "github.com" or host.endswith(".github.com")


async def github_token_for_url(
    session: AsyncSession, user: User, source: str
) -> str | None:
    """Decrypt the user's GitHub token if ``source`` is a GitHub HTTPS URL."""
    if not is_github_https_url(source):
        return None
    identity = await get_github_identity(session, user.id)
    if identity is None:
        return None
    return decrypt_identity_token(identity)


def looks_like_auth_failure(error_message: str) -> bool:
    lowered = error_message.lower()
    auth_markers = (
        "authentication failed",
        "could not read username",
        "terminal prompts disabled",
        "http 401",
        "http 403",
        "403",
        "401",
        "permission denied",
        "repository not found",
    )
    return any(marker in lowered for marker in auth_markers)
