"""Authentication domain (passwords, JWT tokens, register/login services)."""

from app.core.auth.passwords import hash_password, verify_password
from app.core.auth.service import authenticate, get_user_by_id, register_user
from app.core.auth.tokens import (
    AccessTokenClaims,
    create_access_token,
    decode_access_token,
)

__all__ = [
    "AccessTokenClaims",
    "authenticate",
    "create_access_token",
    "decode_access_token",
    "get_user_by_id",
    "hash_password",
    "register_user",
    "verify_password",
]
