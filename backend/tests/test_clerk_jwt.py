"""Tests for Clerk JWT verification module."""

from __future__ import annotations

import base64
import time
from typing import Any
from unittest.mock import patch

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import app.core.oauth.clerk as clerk_mod
from app.core.exceptions import ClerkTokenError, IntegrationConfigurationError
from app.core.oauth.clerk import (
    ClerkClaims,
    clerk_frontend_api_host,
    reset_jwks_cache_for_tests,
    verify_clerk_token,
)

TEST_CLERK_PUBLISHABLE_KEY = "pk_test_c2FtcGxlMTIzLmNsZXJrLmFjY291bnRzLmRldiQ"


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_jwks_cache_for_tests()
    yield
    reset_jwks_cache_for_tests()


def test_clerk_frontend_api_host_decodes_embedded_domain() -> None:
    assert clerk_frontend_api_host(TEST_CLERK_PUBLISHABLE_KEY) == "sample123.clerk.accounts.dev"


def test_missing_publishable_key_raises(monkeypatch: Any) -> None:
    monkeypatch.delenv("VELA_CLERK_PUBLISHABLE_KEY", raising=False)
    with pytest.raises(IntegrationConfigurationError, match="VELA_CLERK_PUBLISHABLE_KEY"):
        clerk_mod._publishable_key()


def _make_rsa_kid() -> tuple[str, rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return "test-clerk-key", private_key


def _jwks_for(kid: str, private_key: rsa.RSAPrivateKey) -> dict[str, object]:
    public_numbers = private_key.public_key().public_numbers()
    n_bytes = public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
    e_bytes = public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")
    return {
        "keys": [{
            "kty": "RSA",
            "alg": "RS256",
            "use": "sig",
            "kid": kid,
            "n": base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode("ascii"),
            "e": base64.urlsafe_b64encode(e_bytes).rstrip(b"=").decode("ascii"),
        }]
    }


def _sign_clerk_token(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str,
    email: str,
    sub: str,
    audience: str,
) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "email": email,
            "sub": sub,
            "aud": audience,
            "iss": "https://sample123.clerk.accounts.dev",
            "exp": now + 600,
            "iat": now,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


@pytest.mark.asyncio
async def test_verify_clerk_token_success_with_real_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)
    kid, private_key = _make_rsa_kid()
    token = _sign_clerk_token(
        private_key,
        kid=kid,
        email="ClerkUser@Example.COM",
        sub="user_2Xabc",
        audience=TEST_CLERK_PUBLISHABLE_KEY,
    )

    async def fake_fetch() -> dict[str, object]:
        return _jwks_for(kid, private_key)

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        claims = await verify_clerk_token(token)

    assert claims == ClerkClaims(email="clerkuser@example.com", external_id="user_2Xabc")


@pytest.mark.asyncio
async def test_verify_clerk_token_missing_email_raises(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)
    kid, private_key = _make_rsa_kid()
    now = int(time.time())
    token = pyjwt.encode(
        {
            "sub": "user_1",
            "aud": TEST_CLERK_PUBLISHABLE_KEY,
            "iss": "https://x",
            "exp": now + 600,
            "iat": now,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    async def fake_fetch() -> dict[str, object]:
        return _jwks_for(kid, private_key)

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with pytest.raises(ClerkTokenError, match="missing the email claim"):
            await verify_clerk_token(token)


@pytest.mark.asyncio
async def test_verify_clerk_token_unknown_kid_raises(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)
    kid, private_key = _make_rsa_kid()
    token = pyjwt.encode(
        {
            "sub": "user_1",
            "aud": TEST_CLERK_PUBLISHABLE_KEY,
            "iss": "https://x",
            "exp": int(time.time()) + 600,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    async def fake_fetch() -> dict[str, object]:
        return _jwks_for(f"{kid}-other", private_key)

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with pytest.raises(ClerkTokenError, match="no matching key"):
            await verify_clerk_token(token)


@pytest.mark.asyncio
async def test_verify_clerk_token_wrong_key_raises(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)
    kid, signer_key = _make_rsa_kid()
    token = _sign_clerk_token(
        signer_key,
        kid=kid,
        email="u@x.com",
        sub="user_1",
        audience=TEST_CLERK_PUBLISHABLE_KEY,
    )
    _, other_key = _make_rsa_kid()

    async def fake_fetch() -> dict[str, object]:
        return _jwks_for(kid, other_key)

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with pytest.raises(ClerkTokenError, match="invalid"):
            await verify_clerk_token(token)


@pytest.mark.asyncio
async def test_fetch_jwks_network_error_raises_clerk_error(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)

    def failing_client(*args: Any, **kwargs: Any) -> Any:
        raise httpx.ConnectError("boom")

    with patch.object(clerk_mod.httpx, "AsyncClient", side_effect=failing_client):
        with pytest.raises(ClerkTokenError, match="temporarily unavailable"):
            await clerk_mod._fetch_jwks()
