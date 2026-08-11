"""Tests for the Clerk token exchange endpoint."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from app.core.oauth.clerk import ClerkClaims


def _mock_clerk_verify() -> ClerkClaims:
    return ClerkClaims(email="clerk-user@example.com", external_id="user_2Xtest")


def _patch_clerk_verify():
    return patch(
        "app.api.routes.auth.verify_clerk_token",
        new=AsyncMock(return_value=_mock_clerk_verify()),
    )


def test_clerk_exchange_creates_new_user(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

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


def test_clerk_exchange_links_existing_user(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

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

            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "fake.clerk.jwt"},
            )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "clerk-user@example.com"


def test_clerk_exchange_missing_config_returns_503(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.delenv("VELA_CLERK_PUBLISHABLE_KEY", raising=False)

    from fastapi.testclient import TestClient

    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/clerk/exchange",
            json={"clerk_token": "fake"},
        )

    assert response.status_code == 503


def test_clerk_exchange_invalid_token_returns_400(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

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


def test_clerk_exchange_account_already_linked_returns_409(db_app: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("VELA_CLERK_PUBLISHABLE_KEY", "pk_test_sample123")

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

        with patch(
            "app.api.routes.auth.verify_clerk_token",
            new=AsyncMock(return_value=mock_verify_different_email("fake")),
        ):
            response = client.post(
                "/api/auth/clerk/exchange",
                json={"clerk_token": "fake.clerk.jwt"},
            )

        assert response.status_code == 409
