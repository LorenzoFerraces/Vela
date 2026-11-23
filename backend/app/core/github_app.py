"""GitHub App signature verification and installation access tokens."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GitHubAppNotConfiguredError
from app.core.security.secrets import decrypt_secret
from app.db.models import GitHubAppInstall, GitHubAppInstallationId


def verify_github_signature(
    payload: bytes, secret: str, signature: str | None
) -> bool:
    """Constant-time check of GitHub's ``X-Hub-Signature-256`` header."""
    if signature is None or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    # Compare bytes: non-ASCII header values are valid latin-1 str but raise
    # TypeError in the str form of compare_digest (unauthenticated 500).
    return hmac.compare_digest(
        signature.removeprefix("sha256=").encode("utf-8"), expected.encode("utf-8")
    )


async def installation_token(session: AsyncSession, project_id: uuid.UUID) -> str:
    """Mint an App JWT and exchange it for a project's installation token."""
    install = (await session.execute(select(GitHubAppInstall))).scalar_one_or_none()
    if install is None:
        raise GitHubAppNotConfiguredError("GitHub App is not configured")
    mapping = (
        await session.execute(
            select(GitHubAppInstallationId).where(
                GitHubAppInstallationId.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    if mapping is None:
        raise GitHubAppNotConfiguredError(
            "No GitHub App installation is linked to this project"
        )
    now = int(time.time())
    assertion = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": install.app_id},
        decrypt_secret(install.private_key_encrypted),
        algorithm="RS256",
    )
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/app/installations/{mapping.installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {assertion}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        return str(response.json()["token"])
