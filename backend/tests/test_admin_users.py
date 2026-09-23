"""Tests for admin and instructor user management."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _stored_user(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> User:
    async def run() -> User:
        async with factory() as session:
            user = await session.get(User, user_id)
            assert user is not None
            return user

    return asyncio.run(run())


def test_student_cannot_list_users(
    db_app: Any, provision_user: Any
) -> None:
    _, token = provision_user("stu-admin-api@example.com", role="student")

    with TestClient(db_app) as client:
        response = client.get("/api/admin/users", headers=_auth(token))

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required."


def test_instructor_cannot_list_users(
    db_app: Any, provision_user: Any
) -> None:
    _, token = provision_user("inst@example.com", role="instructor")

    with TestClient(db_app) as client:
        response = client.get("/api/admin/users", headers=_auth(token))

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required."


def test_admin_lists_users(db_app: Any, provision_user: Any) -> None:
    _, admin_token = provision_user("boss@example.com", role="admin")
    provision_user("kid@example.com", role="student")
    provision_user("teacher@example.com", role="instructor")

    with TestClient(db_app) as client:
        response = client.get("/api/admin/users", headers=_auth(admin_token))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {user["email"] for user in body["users"]} == {
        "boss@example.com",
        "kid@example.com",
        "teacher@example.com",
    }
    assert {user["role"] for user in body["users"]} == {
        "admin",
        "instructor",
        "student",
    }


def test_admin_filters_and_paginates_users(
    db_app: Any, provision_user: Any
) -> None:
    _, admin_token = provision_user("filter-admin@example.com", role="admin")
    provision_user("alpha@example.com", role="student")
    provision_user("beta@example.com", role="student")
    provision_user("filter-teacher@example.com", role="instructor")

    with TestClient(db_app) as client:
        searched = client.get(
            "/api/admin/users?query=alpha", headers=_auth(admin_token)
        )
        filtered = client.get(
            "/api/admin/users?role=student&is_active=true&limit=1&offset=1",
            headers=_auth(admin_token),
        )

    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert [user["email"] for user in searched.json()["users"]] == [
        "alpha@example.com"
    ]
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2
    assert len(filtered.json()["users"]) == 1
    assert filtered.json()["users"][0]["role"] == "student"


def test_student_cannot_create_users(
    db_app: Any, provision_user: Any
) -> None:
    _, token = provision_user("stu-create@example.com", role="student")

    with TestClient(db_app) as client:
        response = client.post(
            "/api/admin/users",
            headers=_auth(token),
            json={
                "email": "forged@example.com",
                "password": "password-min-8-chars",
                "role": "student",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Instructor or admin access required."


def test_instructor_creates_student_and_instructor(
    db_app: Any,
    db_session_factory: async_sessionmaker[AsyncSession],
    provision_user: Any,
) -> None:
    _, token = provision_user("teach@example.com", role="instructor")

    with TestClient(db_app) as client:
        student = client.post(
            "/api/admin/users",
            headers=_auth(token),
            json={
                "email": "new-student@example.com",
                "password": "password-min-8-chars",
                "role": "student",
            },
        )
        instructor = client.post(
            "/api/admin/users",
            headers=_auth(token),
            json={
                "email": "new-instructor@example.com",
                "password": "password-min-8-chars",
                "role": "instructor",
            },
        )
        forbidden = client.post(
            "/api/admin/users",
            headers=_auth(token),
            json={
                "email": "fake-admin@example.com",
                "password": "password-min-8-chars",
                "role": "admin",
            },
        )

    assert student.status_code == 201
    assert student.json()["role"] == "student"
    assert instructor.status_code == 201
    assert instructor.json()["role"] == "instructor"
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Only admins can create admin accounts."
    assert _stored_user(
        db_session_factory, uuid.UUID(student.json()["id"])
    ).personal_project_id is not None
    assert _stored_user(
        db_session_factory, uuid.UUID(instructor.json()["id"])
    ).personal_project_id is not None


def test_admin_creates_admin_and_deactivates(
    db_app: Any,
    db_session_factory: async_sessionmaker[AsyncSession],
    provision_user: Any,
) -> None:
    _, admin_token = provision_user("root2@example.com", role="admin")

    with TestClient(db_app) as client:
        created = client.post(
            "/api/admin/users",
            headers=_auth(admin_token),
            json={
                "email": "second-admin@example.com",
                "password": "password-min-8-chars",
                "role": "admin",
            },
        )
        user_id = created.json()["id"]
        patched = client.patch(
            f"/api/admin/users/{user_id}",
            headers=_auth(admin_token),
            json={"is_active": False},
        )

    assert created.status_code == 201
    assert created.json()["role"] == "admin"
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False
    stored = _stored_user(db_session_factory, uuid.UUID(user_id))
    assert stored.role == "admin"
    assert stored.is_active is False


def test_instructor_cannot_patch_users(
    db_app: Any,
    db_session_factory: async_sessionmaker[AsyncSession],
    provision_user: Any,
) -> None:
    _, instructor_token = provision_user("inst2@example.com", role="instructor")
    victim, _ = provision_user("victim@example.com", role="student")

    with TestClient(db_app) as client:
        role_response = client.patch(
            f"/api/admin/users/{victim.id}",
            headers=_auth(instructor_token),
            json={"role": "admin"},
        )
        status_response = client.patch(
            f"/api/admin/users/{victim.id}",
            headers=_auth(instructor_token),
            json={"is_active": False},
        )

    assert role_response.status_code == 403
    assert role_response.json()["detail"] == "Admin access required."
    assert status_response.status_code == 403
    stored = _stored_user(db_session_factory, victim.id)
    assert stored.role == "student"
    assert stored.is_active is True


def test_admin_patch_returns_404_for_missing_user(
    db_app: Any, provision_user: Any
) -> None:
    _, admin_token = provision_user("missing-admin@example.com", role="admin")

    with TestClient(db_app) as client:
        response = client.patch(
            f"/api/admin/users/{uuid.uuid4()}",
            headers=_auth(admin_token),
            json={"role": "student"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_duplicate_user_email_returns_conflict(
    db_app: Any, provision_user: Any
) -> None:
    _, admin_token = provision_user("duplicate-admin@example.com", role="admin")
    payload = {
        "email": "duplicate@example.com",
        "password": "password-min-8-chars",
        "role": "student",
    }
    duplicate_payload = {
        **payload,
        "email": "  Duplicate@Example.COM  ",
    }

    with TestClient(db_app) as client:
        created = client.post(
            "/api/admin/users", headers=_auth(admin_token), json=payload
        )
        duplicate = client.post(
            "/api/admin/users",
            headers=_auth(admin_token),
            json=duplicate_payload,
        )

    assert created.status_code == 201
    assert created.json()["email"] == "duplicate@example.com"
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "That email is already registered."
