"""Tests for the Clerk token exchange endpoint."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

import app.core.oauth.clerk as clerk_mod
from app.core.exceptions import ProviderConnectionError
from app.core.oauth.clerk import ClerkClaims, reset_jwks_cache_for_tests
from app.db.models import UserOAuthIdentity

TEST_CLERK_PUBLISHABLE_KEY = "pk_test_c2FtcGxlMTIzLmNsZXJrLmFjY291bnRzLmRldiQ"


def _mock_clerk_verify() -> ClerkClaims:
    return ClerkClaims(email="clerk-user@example.com", external_id="user_2Xtest")


def _patch_clerk_verify():
    return patch(
        "app.api.routes.auth.verify_clerk_token",
        new=AsyncMock(return_value=_mock_clerk_verify()),
    )


def _clerk_identities(db_session_factory: Any) -> list[Any]:
    async def run() -> list[Any]:
        async with db_session_factory() as session:
            result = await session.execute(
                select(UserOAuthIdentity).where(
                    UserOAuthIdentity.provider == "clerk"
                )
            )
            return list(result.scalars().all())

    return asyncio.run(run())


def test_clerk_exchange_creates_new_user(
    db_app: Any, db_session_factory: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)

    from fastapi.testclient import TestClient

    with _patch_clerk_verify():
        with TestClient(db_app) as client:
            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "fake.clerk.jwt"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str)
    assert body["user"]["email"] == "clerk-user@example.com"

    identities = _clerk_identities(db_session_factory)
    assert len(identities) == 1
    assert identities[0].provider == "clerk"
    assert identities[0].provider_subject == "user_2Xtest"
    assert identities[0].user_id == uuid.UUID(body["user"]["id"])


def test_clerk_exchange_links_existing_user(
    db_app: Any, db_session_factory: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)

    from fastapi.testclient import TestClient

    with _patch_clerk_verify():
        with TestClient(db_app) as client:
            reg = client.post(
                "/api/auth/register",
                json={
                    "email": "clerk-user@example.com",
                    "password": "supersecret123",
                },
            )
            assert reg.status_code == 201
            registered_user_id = uuid.UUID(reg.json()["user"]["id"])

            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "fake.clerk.jwt"},
            )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "clerk-user@example.com"

    identities = _clerk_identities(db_session_factory)
    assert len(identities) == 1
    assert identities[0].provider == "clerk"
    assert identities[0].provider_subject == "user_2Xtest"
    assert identities[0].user_id == registered_user_id


def test_clerk_exchange_missing_config_returns_503(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.delenv("VELA_CLERK_PUBLISHABLE_KEY", raising=False)

    from fastapi.testclient import TestClient

    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/clerk/exchange",
            json={"clerk_token": "fake"},
        )

    assert response.status_code == 503


def test_clerk_exchange_jwks_provider_failure_returns_503(
    db_app: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)
    reset_jwks_cache_for_tests()

    from fastapi.testclient import TestClient

    async def failing_fetch() -> dict[str, object]:
        raise ProviderConnectionError("Clerk is temporarily unavailable.")

    with patch.object(clerk_mod, "_fetch_jwks", new=failing_fetch):
        with TestClient(db_app) as client:
            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "fake.clerk.jwt"},
            )

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_clerk_exchange_invalid_token_returns_400(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)

    from app.core.exceptions import ClerkTokenError
    from fastapi.testclient import TestClient

    async def raise_clerk_error(_token: str):
        raise ClerkTokenError("Clerk token verification failed: bad signature")

    with patch(
        "app.api.routes.auth.verify_clerk_token", new=raise_clerk_error
    ):
        with TestClient(db_app) as client:
            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "bad.token"},
            )

    assert response.status_code == 400


def test_clerk_exchange_empty_body_returns_422(db_app: Any) -> None:
    from fastapi.testclient import TestClient

    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/clerk/exchange",
            json={},
        )

    assert response.status_code == 422


def test_clerk_exchange_account_already_linked_returns_409(
    db_app: Any, db_session_factory: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", TEST_CLERK_PUBLISHABLE_KEY)

    def mock_verify_different_email(_token: str) -> ClerkClaims:
        return ClerkClaims(email="other@example.com", external_id="user_2Xtest")

    from fastapi.testclient import TestClient

    with TestClient(db_app) as client:
        with _patch_clerk_verify():
            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "fake.clerk.jwt"},
            )
            assert response.status_code == 200

        original = _clerk_identities(db_session_factory)[0]

        with patch(
            "app.api.routes.auth.verify_clerk_token",
            new=AsyncMock(return_value=mock_verify_different_email("fake")),
        ):
            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "fake.clerk.jwt"},
            )

        assert response.status_code == 409

    identities = _clerk_identities(db_session_factory)
    assert len(identities) == 1
    assert identities[0].id == original.id
    assert identities[0].user_id == original.user_id
    assert identities[0].provider == "clerk"
    assert identities[0].provider_subject == "user_2Xtest"
