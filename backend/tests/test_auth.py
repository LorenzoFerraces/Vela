"""Tests for the email + password auth flow."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.core.auth.tokens import create_access_token


def test_register_returns_token_and_user(db_app: Any) -> None:
    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/register",
            json={"email": "newuser@example.com", "password": "supersecret123"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert body["user"]["email"] == "newuser@example.com"
    assert "password_hash" not in body["user"]


def test_register_rejects_duplicate_email(db_app: Any) -> None:
    with TestClient(db_app) as client:
        first = client.post(
            "/api/auth/register",
            json={"email": "dup@example.com", "password": "supersecret123"},
        )
        assert first.status_code == 201
        second = client.post(
            "/api/auth/register",
            json={"email": "dup@example.com", "password": "anotherpass456"},
        )
    assert second.status_code == 409
    assert "already" in second.json()["detail"].lower()


def test_register_rejects_short_password(db_app: Any) -> None:
    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/register",
            json={"email": "short@example.com", "password": "abc"},
        )
    assert response.status_code == 422


def test_login_success(db_app: Any) -> None:
    with TestClient(db_app) as client:
        client.post(
            "/api/auth/register",
            json={"email": "login@example.com", "password": "correctpassword"},
        )
        response = client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "correctpassword"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "login@example.com"
    assert body["access_token"]


def test_login_normalizes_email_case(db_app: Any) -> None:
    with TestClient(db_app) as client:
        client.post(
            "/api/auth/register",
            json={"email": "Mixed@Example.com", "password": "correctpassword"},
        )
        response = client.post(
            "/api/auth/login",
            json={"email": "mixed@example.com", "password": "correctpassword"},
        )
    assert response.status_code == 200


def test_login_wrong_password(db_app: Any) -> None:
    with TestClient(db_app) as client:
        client.post(
            "/api/auth/register",
            json={"email": "bad@example.com", "password": "correctpassword"},
        )
        response = client.post(
            "/api/auth/login",
            json={"email": "bad@example.com", "password": "wrongpassword"},
        )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate", "").lower() == "bearer"


def test_login_unknown_user(db_app: Any) -> None:
    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever12345"},
        )
    assert response.status_code == 401


def test_me_returns_current_user(db_app: Any) -> None:
    with TestClient(db_app) as client:
        registered = client.post(
            "/api/auth/register",
            json={"email": "me@example.com", "password": "supersecret123"},
        ).json()
        token = registered["access_token"]
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


def test_me_without_token_is_unauthorized(db_app: Any) -> None:
    with TestClient(db_app) as client:
        response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_with_invalid_token_is_unauthorized(db_app: Any) -> None:
    with TestClient(db_app) as client:
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    assert response.status_code == 401


def test_token_for_unknown_user_is_rejected(db_app: Any) -> None:
    """A signed token for a deleted/nonexistent user must not authenticate."""
    import uuid

    rogue_token = create_access_token(uuid.uuid4())
    with TestClient(db_app) as client:
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {rogue_token}"},
        )
    assert response.status_code == 401
