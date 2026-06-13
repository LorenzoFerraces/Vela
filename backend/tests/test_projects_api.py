"""Tests for project and invitation API."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str, password: str = "password-min-8-chars") -> str:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_shared_project(db_app: Any) -> None:
    with TestClient(db_app) as client:
        token = _register(client, "creator@example.com")
        client.headers.update(_auth_headers(token))

        create_response = client.post(
            "/api/projects/",
            json={"name": "Platform team"},
        )
        assert create_response.status_code == 201, create_response.text
        created = create_response.json()
        assert created["name"] == "Platform team"
        assert created["is_personal"] is False
        assert created["role"] == "owner"

        projects = client.get("/api/projects/").json()
        assert len(projects) == 2
        shared = next(project for project in projects if not project["is_personal"])
        assert shared["name"] == "Platform team"


def test_member_can_leave_shared_project(db_app: Any) -> None:
    with TestClient(db_app) as owner_client, TestClient(db_app) as member_client:
        owner_token = _register(owner_client, "leave-owner@example.com")
        member_token = _register(member_client, "leave-member@example.com")
        owner_client.headers.update(_auth_headers(owner_token))
        member_client.headers.update(_auth_headers(member_token))

        project_id = owner_client.post(
            "/api/projects/",
            json={"name": "Temporary team"},
        ).json()["id"]

        invitation = owner_client.post(
            f"/api/projects/{project_id}/invitations",
            json={"email": "leave-member@example.com", "role": "viewer"},
        ).json()
        invitation_id = member_client.get("/api/projects/invitations/incoming").json()[0]["id"]
        member_client.post(f"/api/projects/invitations/{invitation_id}/accept")

        leave_response = member_client.post(f"/api/projects/{project_id}/leave")
        assert leave_response.status_code == 204

        member_projects = member_client.get("/api/projects/").json()
        assert all(project["id"] != project_id for project in member_projects)


def test_register_creates_personal_project(db_app: Any) -> None:
    with TestClient(db_app) as client:
        token = _register(client, "solo@example.com")
        response = client.get("/api/projects/", headers=_auth_headers(token))
    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["is_personal"] is True
    assert projects[0]["role"] == "owner"


def test_invite_requires_accept_before_membership(db_app: Any) -> None:
    with TestClient(db_app) as owner_client, TestClient(db_app) as invitee_client:
        owner_token = _register(owner_client, "owner@example.com")
        invitee_token = _register(invitee_client, "invitee@example.com")
        owner_client.headers.update(_auth_headers(owner_token))
        invitee_client.headers.update(_auth_headers(invitee_token))

        owner_projects = owner_client.get("/api/projects/").json()
        personal_project_id = owner_projects[0]["id"]

        invite_response = owner_client.post(
            f"/api/projects/{personal_project_id}/invitations",
            json={"email": "invitee@example.com", "role": "viewer"},
        )
        assert invite_response.status_code == 201

        members_before = owner_client.get(
            f"/api/projects/{personal_project_id}/members",
        ).json()
        invitee_emails = [member["email"] for member in members_before]
        assert "invitee@example.com" not in invitee_emails

        invitee_projects_before = invitee_client.get("/api/projects/").json()
        assert len(invitee_projects_before) == 1

        accept_response = invitee_client.post(
            f"/api/projects/invitations/{invite_response.json()['id']}/accept",
        )
        assert accept_response.status_code == 200
        assert accept_response.json()["role"] == "viewer"

        members_after = owner_client.get(
            f"/api/projects/{personal_project_id}/members",
        ).json()
        assert any(member["email"] == "invitee@example.com" for member in members_after)

        invitee_projects_after = invitee_client.get("/api/projects/").json()
        assert len(invitee_projects_after) == 2


def test_reject_invitation_does_not_add_member(db_app: Any) -> None:
    with TestClient(db_app) as owner_client, TestClient(db_app) as invitee_client:
        owner_token = _register(owner_client, "reject-owner@example.com")
        invitee_token = _register(invitee_client, "reject-invitee@example.com")
        owner_client.headers.update(_auth_headers(owner_token))
        invitee_client.headers.update(_auth_headers(invitee_token))

        project_id = owner_client.get("/api/projects/").json()[0]["id"]

        invitation = owner_client.post(
            f"/api/projects/{project_id}/invitations",
            json={"email": "reject-invitee@example.com", "role": "operator"},
        ).json()

        reject_response = invitee_client.post(
            f"/api/projects/invitations/{invitation['id']}/reject",
        )
        assert reject_response.status_code == 204

        members = owner_client.get(f"/api/projects/{project_id}/members").json()
        assert "reject-invitee@example.com" not in [member["email"] for member in members]


def test_non_owner_cannot_invite(db_app: Any) -> None:
    with (
        TestClient(db_app) as owner_client,
        TestClient(db_app) as invitee_client,
        TestClient(db_app) as stranger_client,
    ):
        owner_token = _register(owner_client, "perm-owner@example.com")
        invitee_token = _register(invitee_client, "perm-invitee@example.com")
        stranger_token = _register(stranger_client, "stranger@example.com")
        owner_client.headers.update(_auth_headers(owner_token))
        invitee_client.headers.update(_auth_headers(invitee_token))
        stranger_client.headers.update(_auth_headers(stranger_token))

        project_id = owner_client.get("/api/projects/").json()[0]["id"]

        owner_client.post(
            f"/api/projects/{project_id}/invitations",
            json={"email": "perm-invitee@example.com", "role": "viewer"},
        )
        invitation_id = invitee_client.get("/api/projects/invitations/incoming").json()[0]["id"]
        invitee_client.post(f"/api/projects/invitations/{invitation_id}/accept")

        forbidden = stranger_client.post(
            f"/api/projects/{project_id}/invitations",
            json={"email": "stranger@example.com", "role": "viewer"},
        )
        assert forbidden.status_code == 404


def test_unknown_email_returns_400(db_app: Any) -> None:
    with TestClient(db_app) as client:
        token = _register(client, "unknown-owner@example.com")
        client.headers.update(_auth_headers(token))
        project_id = client.get("/api/projects/").json()[0]["id"]

        response = client.post(
            f"/api/projects/{project_id}/invitations",
            json={"email": "missing-user@example.com", "role": "viewer"},
        )
    assert response.status_code == 400


def test_cancelled_invite_cannot_be_accepted(db_app: Any) -> None:
    with TestClient(db_app) as owner_client, TestClient(db_app) as invitee_client:
        owner_token = _register(owner_client, "cancel-owner@example.com")
        invitee_token = _register(invitee_client, "cancel-invitee@example.com")
        owner_client.headers.update(_auth_headers(owner_token))
        invitee_client.headers.update(_auth_headers(invitee_token))

        project_id = owner_client.get("/api/projects/").json()[0]["id"]

        invitation = owner_client.post(
            f"/api/projects/{project_id}/invitations",
            json={"email": "cancel-invitee@example.com", "role": "viewer"},
        ).json()

        cancel_response = owner_client.delete(
            f"/api/projects/{project_id}/invitations/{invitation['id']}",
        )
        assert cancel_response.status_code == 204

        accept_response = invitee_client.post(
            f"/api/projects/invitations/{invitation['id']}/accept",
        )
        assert accept_response.status_code == 409
