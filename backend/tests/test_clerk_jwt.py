"""Tests for Clerk JWT verification module."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import app.core.oauth.clerk as clerk_mod
from app.core.exceptions import ClerkTokenError, IntegrationConfigurationError
from app.core.oauth.clerk import (
    ClerkClaims,
    reset_jwks_cache_for_tests,
    verify_clerk_token,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_jwks_cache_for_tests()
    yield
    reset_jwks_cache_for_tests()


def test_missing_publishable_key_raises(monkeypatch: Any) -> None:
    monkeypatch.delenv("VELA_CLERK_PUBLISHABLE_KEY", raising=False)
    with pytest.raises(IntegrationConfigurationError, match="VELA_CLERK_PUBLISHABLE_KEY"):
        clerk_mod._publishable_key()


@pytest.mark.asyncio
async def test_verify_clerk_token_success(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

    async def fake_fetch() -> dict[str, object]:
        return {"keys": [{"kty": "RSA", "alg": "RS256", "use": "sig"}]}

    fake_payload = {
        "email": "ClerkUser@Example.COM",
        "sub": "user_2Xabc",
        "iss": "https://pk_test_sample123.clerk.accounts.clerkdev.com",
        "aud": "pk_test_sample123",
    }

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with patch("app.core.oauth.clerk.jwt.decode", return_value=fake_payload):
            claims = await verify_clerk_token("fake.token.here")

    assert claims == ClerkClaims(email="clerkuser@example.com", external_id="user_2Xabc")


@pytest.mark.asyncio
async def test_verify_clerk_token_missing_email_raises(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

    async def fake_fetch() -> dict[str, object]:
        return {"keys": [{"kty": "RSA", "alg": "RS256"}]}

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with patch("app.core.oauth.clerk.jwt.decode", return_value={"sub": "user_1"}):
            with pytest.raises(ClerkTokenError, match="missing the email claim"):
                await verify_clerk_token("fake.token")


@pytest.mark.asyncio
async def test_verify_clerk_token_invalid_signature_raises(monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

    async def fake_fetch() -> dict[str, object]:
        return {"keys": [{"kty": "RSA", "alg": "RS256"}]}

    from jwt import InvalidTokenError

    with patch.object(clerk_mod, "_fetch_jwks", new=fake_fetch):
        with patch("app.core.oauth.clerk.jwt.decode", side_effect=InvalidTokenError("bad sig")):
            with pytest.raises(ClerkTokenError, match="Clerk token verification failed"):
                await verify_clerk_token("bad.token")
