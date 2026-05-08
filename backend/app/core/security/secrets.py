"""Symmetric encryption for third-party access tokens stored at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) with a key from
``VELA_TOKEN_ENCRYPTION_KEY``. Generate one with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import os
from threading import Lock

from cryptography.fernet import Fernet, InvalidToken

_TOKEN_KEY_ENV = "VELA_TOKEN_ENCRYPTION_KEY"

_cipher: Fernet | None = None
_cipher_lock = Lock()


def _load_cipher() -> Fernet:
    raw = os.environ.get(_TOKEN_KEY_ENV, "").strip()
    if not raw:
        msg = (
            f"{_TOKEN_KEY_ENV} is not set. Configure backend/.env with a Fernet key — "
            'generate one: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())".'
        )
        raise RuntimeError(msg)
    try:
        return Fernet(raw.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"{_TOKEN_KEY_ENV} is not a valid Fernet key (must be 32 url-safe base64 bytes)."
        ) from exc


def _get_cipher() -> Fernet:
    global _cipher
    with _cipher_lock:
        if _cipher is None:
            _cipher = _load_cipher()
        return _cipher


def encrypt_secret(plaintext: str) -> bytes:
    """Encrypt ``plaintext`` for storage in a ``LargeBinary`` column."""
    return _get_cipher().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes) -> str:
    """Decrypt a value previously produced by :func:`encrypt_secret`."""
    try:
        return _get_cipher().decrypt(bytes(ciphertext)).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "Stored token could not be decrypted; the encryption key likely changed."
        ) from exc


def reset_token_cipher_for_tests() -> None:
    """Drop the cached cipher so tests can swap ``VELA_TOKEN_ENCRYPTION_KEY``."""
    global _cipher
    with _cipher_lock:
        _cipher = None
