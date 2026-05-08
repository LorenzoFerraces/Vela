"""Short-lived signed state tokens for OAuth callbacks.

The OAuth callback is a top-level browser navigation from GitHub — the API does
not see the user's bearer token on that request. Instead the start endpoint signs
a JWT with the current user id and a nonce, the browser carries it in the
``state`` query param, and the callback decodes it. Reusing
``VELA_AUTH_SECRET`` and PyJWT keeps the dependency surface small.
"""

from __future__ import annotations

import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError

from app.core.exceptions import GitHubOAuthError

_STATE_TYPE = "github_oauth_state"
_DEFAULT_TTL_SECONDS = 600  # 10 minutes — covers slow user consent screens
_ALGORITHM = "HS256"


@dataclass(frozen=True)
class StateClaims:
    user_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime
    nonce: str


def _secret() -> str:
    secret = os.environ.get("VELA_AUTH_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "VELA_AUTH_SECRET is not set; cannot sign GitHub OAuth state."
        )
    return secret


def encode_state(user_id: uuid.UUID, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> str:
    """Sign a short-lived state token tying the OAuth dance to ``user_id``."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    payload = {
        "sub": str(user_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "type": _STATE_TYPE,
        "nonce": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_state(token: str) -> StateClaims:
    """Validate the signed state and return its claims, or raise :class:`GitHubOAuthError`."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except InvalidTokenError as exc:
        raise GitHubOAuthError("invalid_state", "OAuth state is invalid or expired.") from exc

    if payload.get("type") != _STATE_TYPE:
        raise GitHubOAuthError("wrong_state_type", "OAuth state has the wrong type.")

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise GitHubOAuthError("malformed_state", "OAuth state is malformed.")
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise GitHubOAuthError("malformed_state", "OAuth state is malformed.") from exc

    issued_at_raw = payload.get("iat")
    expires_at_raw = payload.get("exp")
    nonce = payload.get("nonce")
    if (
        not isinstance(issued_at_raw, int)
        or not isinstance(expires_at_raw, int)
        or not isinstance(nonce, str)
    ):
        raise GitHubOAuthError("malformed_state", "OAuth state is malformed.")

    return StateClaims(
        user_id=user_id,
        issued_at=datetime.fromtimestamp(issued_at_raw, tz=timezone.utc),
        expires_at=datetime.fromtimestamp(expires_at_raw, tz=timezone.utc),
        nonce=nonce,
    )
