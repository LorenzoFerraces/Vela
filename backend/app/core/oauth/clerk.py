"""Clerk JWT verification — fetches JWK set, verifies tokens, extracts claims."""

from __future__ import annotations

import base64
import binascii
import logging
import os
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt import InvalidTokenError

from app.core.exceptions import (
    ClerkTokenError,
    IntegrationConfigurationError,
    ProviderConnectionError,
)

_JWKS_CACHE_TTL_SECONDS = 3600
_CLERK_USER_API_URL = "https://api.clerk.com/v1/users/{user_id}"

logger = logging.getLogger(__name__)

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
    try:
        domain = base64.urlsafe_b64decode(padded).decode("utf-8")
    except (binascii.Error, ValueError) as exc:
        raise IntegrationConfigurationError(
            "VELA_CLERK_PUBLISHABLE_KEY is malformed (expected a valid Clerk "
            "publishable key)."
        ) from exc
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
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_jwks_url())
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderConnectionError("Clerk is temporarily unavailable.") from exc
    return resp.json()


async def _get_jwks(*, force_refresh: bool = False) -> dict[str, object]:
    global _jwks_cache, _jwks_loaded_at
    now = time.time()
    if (
        force_refresh
        or _jwks_cache is None
        or (now - _jwks_loaded_at) > _JWKS_CACHE_TTL_SECONDS
    ):
        _jwks_cache = await _fetch_jwks()
        _jwks_loaded_at = now
    return _jwks_cache


def _allowed_origins() -> frozenset[str]:
    raw = os.environ.get("VELA_ALLOWED_ORIGINS", "")
    return frozenset(origin.strip() for origin in raw.split(",") if origin.strip())


_azp_warning_logged = False


def _warn_if_azp_unenforced() -> None:
    """Warn once when Clerk is configured but azp enforcement is disabled."""
    global _azp_warning_logged
    if _azp_warning_logged:
        return
    _azp_warning_logged = True
    has_clerk = bool(os.environ.get("VELA_CLERK_PUBLISHABLE_KEY", "").strip())
    if has_clerk and not _allowed_origins():
        logger.warning(
            "VELA_ALLOWED_ORIGINS is empty; Clerk token azp claims are not enforced."
        )


def _secret_key() -> str:
    return os.environ.get("VELA_CLERK_SECRET_KEY", "").strip()


async def _fetch_clerk_email(external_id: str) -> str:
    """Resolve the account's email through Clerk's Users API.

    Used when the session token carries no ``email`` claim (common with custom
    JWT templates). Requires ``VELA_CLERK_SECRET_KEY``.
    """
    secret_key = _secret_key()
    if not secret_key:
        raise IntegrationConfigurationError(
            "Clerk session token has no email claim; set VELA_CLERK_SECRET_KEY so "
            "the API can resolve the account's email, or add the email claim to "
            "the session token."
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _CLERK_USER_API_URL.format(user_id=external_id),
                headers={"Authorization": f"Bearer {secret_key}"},
            )
    except httpx.HTTPError as exc:
        raise ProviderConnectionError("Clerk is temporarily unavailable.") from exc
    if resp.status_code in (401, 403):
        raise IntegrationConfigurationError(
            "Clerk rejected VELA_CLERK_SECRET_KEY (check the key)."
        )
    if resp.status_code == 404:
        raise ClerkTokenError("Clerk account no longer exists.")
    if resp.status_code >= 400:
        raise ProviderConnectionError("Clerk is temporarily unavailable.")
    # The user endpoint returns the user object directly (no "data" wrapper).
    body = resp.json()
    user = body.get("data") if isinstance(body.get("data"), dict) else body
    addresses = [a for a in (user.get("email_addresses") or []) if isinstance(a, dict)]
    verified = [
        a
        for a in addresses
        if isinstance(a.get("verification"), dict)
        and a["verification"].get("status") == "verified"
    ]
    chosen = verified or addresses
    email = chosen[0].get("email_address") if chosen else None
    if not isinstance(email, str) or not email:
        raise ClerkTokenError("Clerk account has no email address.")
    return email.strip().lower()


async def verify_clerk_token(token: str) -> ClerkClaims:
    """Verify a Clerk frontend JWT and return extracted claims.

    Clerk's default session tokens carry no ``aud`` claim, so those are bound
    to the app via their issuer (and the JWKS signature). A token that does
    carry an ``aud`` claim must include the publishable key. When the token
    also lacks an ``email`` claim, the account's email is resolved via Clerk's
    Users API using ``VELA_CLERK_SECRET_KEY``.

    Raises ``ClerkTokenError`` on invalid signature, expiry, issuer, audience,
    azp, or missing required claims.
    """
    _warn_if_azp_unenforced()
    publishable_key = _publishable_key()
    jwks = await _get_jwks()

    try:
        kid = jwt.get_unverified_header(token).get("kid")
        jwk_set = jwt.PyJWKSet.from_dict(jwks)
        try:
            jwk = jwk_set[kid]  # type: ignore[index]
        except KeyError:
            jwks = await _get_jwks(force_refresh=True)
            jwk_set = jwt.PyJWKSet.from_dict(jwks)
            try:
                jwk = jwk_set[kid]  # type: ignore[index]
            except KeyError as exc:
                raise ClerkTokenError(
                    "Clerk token has no matching key (kid not in JWKS)."
                ) from exc
        payload = jwt.decode(
            token,
            key=jwk,
            algorithms=["RS256"],
            issuer=f"https://{clerk_frontend_api_host(publishable_key)}",
            options={
                "require": ["exp", "nbf", "iss", "sub"],
                # Clerk default session tokens omit "aud"; PyJWT 2.13+ rejects
                # aud-carrying tokens unless the audience is verified, so opt out.
                "verify_aud": False,
            },
        )
    except InvalidTokenError as exc:
        logger.warning(
            "Clerk token verification failed (%s): %s", type(exc).__name__, exc
        )
        raise ClerkTokenError(
            "Clerk token is invalid (signature, expiry, audience, or issuer)."
        ) from exc

    # Signature is verified, so manual comparison of the claim is safe.
    aud = payload.get("aud")
    if aud is not None:
        aud_values = aud if isinstance(aud, list) else [aud]
        if publishable_key not in aud_values:
            raise ClerkTokenError("Clerk token audience does not match this app.")

    external_id = payload.get("sub")
    if not isinstance(external_id, str) or not external_id:
        raise ClerkTokenError("Clerk token is missing the sub claim.")

    email = payload.get("email")
    if not isinstance(email, str) or not email:
        email = await _fetch_clerk_email(external_id)

    allowed_origins = _allowed_origins()
    azp = payload.get("azp")
    if allowed_origins and azp is not None and azp not in allowed_origins:
        raise ClerkTokenError("Clerk token azp is not an allowed origin.")

    return ClerkClaims(email=email.strip().lower(), external_id=external_id)


def reset_jwks_cache_for_tests() -> None:
    """Clear the JWK cache so tests can inject their own keys."""
    global _jwks_cache, _jwks_loaded_at
    _jwks_cache = None
    _jwks_loaded_at = 0.0
