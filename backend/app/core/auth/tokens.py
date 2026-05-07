"""JWT access tokens for the Vela API."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError

from app.core.exceptions import NotAuthenticatedError

_ACCESS_TOKEN_TYPE = "access"
_DEFAULT_TTL_MINUTES = 60
_ALGORITHM = "HS256"


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime


def _secret() -> str:
    secret = os.environ.get("VELA_AUTH_SECRET", "").strip()
    if not secret:
        msg = (
            "VELA_AUTH_SECRET is not set. Configure backend/.env with a long random secret "
            "used to sign auth tokens."
        )
        raise RuntimeError(msg)
    return secret


def _ttl() -> timedelta:
    raw = os.environ.get("VELA_AUTH_ACCESS_TOKEN_TTL_MINUTES", "").strip()
    if not raw:
        return timedelta(minutes=_DEFAULT_TTL_MINUTES)
    try:
        minutes = int(raw)
    except ValueError:
        return timedelta(minutes=_DEFAULT_TTL_MINUTES)
    if minutes <= 0:
        return timedelta(minutes=_DEFAULT_TTL_MINUTES)
    return timedelta(minutes=minutes)


def create_access_token(user_id: uuid.UUID) -> str:
    """Sign a short-lived JWT for ``user_id``."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + _ttl()
    payload = {
        "sub": str(user_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "type": _ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> AccessTokenClaims:
    """Validate the JWT signature, expiry, and type; return parsed claims."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except InvalidTokenError as exc:
        raise NotAuthenticatedError("Invalid or expired token.") from exc

    if payload.get("type") != _ACCESS_TOKEN_TYPE:
        raise NotAuthenticatedError("Wrong token type.")

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise NotAuthenticatedError("Malformed token.")
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise NotAuthenticatedError("Malformed token.") from exc

    issued_at_raw = payload.get("iat")
    expires_at_raw = payload.get("exp")
    if not isinstance(issued_at_raw, int) or not isinstance(expires_at_raw, int):
        raise NotAuthenticatedError("Malformed token.")

    return AccessTokenClaims(
        user_id=user_id,
        issued_at=datetime.fromtimestamp(issued_at_raw, tz=timezone.utc),
        expires_at=datetime.fromtimestamp(expires_at_raw, tz=timezone.utc),
    )
