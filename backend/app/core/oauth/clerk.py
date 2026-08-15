"""Clerk JWT verification — fetches JWK set, verifies tokens, extracts claims."""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt import InvalidTokenError

from app.core.exceptions import ClerkTokenError, IntegrationConfigurationError

_JWKS_CACHE_TTL_SECONDS = 3600

_jwks_cache: dict[str, object] | None = None
_jwks_loaded_at: float = 0.0


@dataclass(frozen=True, slots=True)
class ClerkClaims:
    email: str
    external_id: str


def clerk_frontend_api_host(publishable_key: str) -> str:
    """Decode the Clerk Frontend API hostname embedded in a publishable key."""
    parts = publishable_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "pk" or not parts[2]:
        raise IntegrationConfigurationError(
            "VELA_CLERK_PUBLISHABLE_KEY is not a valid Clerk publishable key."
        )
    encoded = parts[2]
    padded = encoded + "=" * (-len(encoded) % 4)
    domain = base64.urlsafe_b64decode(padded).decode("utf-8")
    return domain.rstrip("$")


def _publishable_key() -> str:
    pk = os.environ.get("VELA_CLERK_PUBLISHABLE_KEY", "").strip()
    if not pk:
        raise IntegrationConfigurationError(
            "Clerk is not configured. Set VELA_CLERK_PUBLISHABLE_KEY in backend/.env."
        )
    return pk


def clerk_available() -> tuple[bool, str | None, str | None]:
    pk = os.environ.get("VELA_CLERK_PUBLISHABLE_KEY", "").strip()
    if not pk:
        return (False, None, None)
    try:
        return (True, pk, clerk_frontend_api_host(pk))
    except IntegrationConfigurationError:
        return (False, None, None)


def _jwks_url() -> str:
    host = clerk_frontend_api_host(_publishable_key())
    return f"https://{host}/.well-known/jwks.json"


async def _fetch_jwks() -> dict[str, object]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_jwks_url())
    resp.raise_for_status()
    return resp.json()


async def _get_jwks() -> dict[str, object]:
    global _jwks_cache, _jwks_loaded_at
    now = time.time()
    if _jwks_cache is None or (now - _jwks_loaded_at) > _JWKS_CACHE_TTL_SECONDS:
        _jwks_cache = await _fetch_jwks()
        _jwks_loaded_at = now
    return _jwks_cache


async def verify_clerk_token(token: str) -> ClerkClaims:
    """Verify a Clerk frontend JWT and return extracted claims.

    Raises ``ClerkTokenError`` on invalid signature, expiry, or missing claims.
    """
    jwks = await _get_jwks()

    try:
        payload = jwt.decode(
            token,
            key=jwks,
            options={"verify_aud": True},
            algorithms=["RS256"],
            audience=_publishable_key(),
        )
    except InvalidTokenError as exc:
        raise ClerkTokenError("Clerk authentication failed.") from exc

    email = payload.get("email")
    if not isinstance(email, str) or not email:
        raise ClerkTokenError("Clerk token is missing the email claim.")

    external_id = payload.get("sub", "")
    if not isinstance(external_id, str):
        external_id = str(external_id)

    return ClerkClaims(email=email.strip().lower(), external_id=external_id)


def reset_jwks_cache_for_tests() -> None:
    """Clear the JWK cache so tests can inject their own keys."""
    global _jwks_cache, _jwks_loaded_at
    _jwks_cache = None
    _jwks_loaded_at = 0.0
