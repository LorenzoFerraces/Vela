"""Tests for the email + password auth flow."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.core.auth.tokens import create_access_token


def test_register_disabled_returns_403(db_app: Any) -> None:
    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/register",
            json={"email": "nope@example.com", "password": "password-min-8-chars"},
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "Registration disabled"


def test_deactivated_login_and_token_rejected(
    db_app: Any, seeded_user: Any, db_session_factory: Any
) -> None:
    import asyncio

    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/login",
            json={
                "email": seeded_user.email,
                "password": "correct-horse-battery-staple",
            },
        )
        assert response.status_code == 200
        token = response.json()["access_token"]

        async def deactivate() -> None:
            from sqlalchemy import select

            from app.db.models import User

            async with db_session_factory() as session:
                user = await session.scalar(select(User).where(User.id == seeded_user.id))
                assert user is not None
                user.is_active = False
                await session.commit()

        asyncio.run(deactivate())

        login = client.post(
            "/api/auth/login",
            json={
                "email": seeded_user.email,
                "password": "correct-horse-battery-staple",
            },
        )
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert login.status_code == 403
    assert login.json() == {
        "detail": "Account deactivated.",
        "code": "account_deactivated",
    }
    assert me.status_code == 403
    assert me.json() == {
        "detail": "Account deactivated.",
        "code": "account_deactivated",
    }


def test_login_returns_token_and_user(db_app: Any, seeded_user: Any) -> None:
    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/login",
            json={
                "email": seeded_user.email,
                "password": "correct-horse-battery-staple",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == seeded_user.email
    assert body["access_token"]


def test_login_rejects_unknown_email(db_app: Any) -> None:
    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever12345"},
        )
    assert response.status_code == 401


def test_login_rejects_bad_password(db_app: Any, seeded_user: Any) -> None:
    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": seeded_user.email, "password": "wrongpassword"},
        )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate", "").lower() == "bearer"


def test_login_normalizes_email_case(db_app: Any, seeded_user: Any) -> None:
    with TestClient(db_app) as client:
        response = client.post(
            "/api/auth/login",
            json={
                "email": seeded_user.email.upper(),
                "password": "correct-horse-battery-staple",
            },
        )
    assert response.status_code == 200


def test_me_returns_current_user(db_app: Any, seeded_user: Any) -> None:
    with TestClient(db_app) as client:
        token = create_access_token(seeded_user.id)
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["email"] == seeded_user.email


def test_me_without_token_is_unauthorized(db_app: Any) -> None:
    with TestClient(db_app) as client:
        response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_includes_role(db_app: Any, seeded_user: Any) -> None:
    with TestClient(db_app) as client:
        token = create_access_token(seeded_user.id)
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "student"


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
