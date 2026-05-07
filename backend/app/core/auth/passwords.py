"""Password hashing helpers (bcrypt).

bcrypt has a 72-byte input limit; we pre-hash the user password with SHA-256
so any input is reduced to a fixed 32-byte digest before bcrypt sees it.
"""

from __future__ import annotations

import hashlib

import bcrypt


def _to_bcrypt_input(plain_password: str) -> bytes:
    return hashlib.sha256(plain_password.encode("utf-8")).digest()


def hash_password(plain_password: str) -> str:
    digest = _to_bcrypt_input(plain_password)
    return bcrypt.hashpw(digest, bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, password_hash: str) -> bool:
    digest = _to_bcrypt_input(plain_password)
    try:
        return bcrypt.checkpw(digest, password_hash.encode("ascii"))
    except ValueError:
        return False
