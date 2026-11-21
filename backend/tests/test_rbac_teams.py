"""Role-based access control for project team management."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def db_client(db_app: Any):
    """Yield a TestClient with the app lifespan running."""
    with TestClient(db_app) as client:
        yield client


def _auth(token: str) -> dict[str, str]:
    """Return a Bearer auth header for the token."""
    return {"Authorization": f"Bearer {token}"}


def _invite_and_accept_member(
    db_client: Any,
    provision_user: Any,
    *,
    owner_token: str,
    instructor_token: str,
    member_email: str,
) -> Any:
    """Provision a student, invite and accept into the owner's project; return ids."""
    member, member_token = provision_user(member_email, role="student")
    project_id = db_client.get(
        "/api/projects", headers=_auth(owner_token)
    ).json()[0]["id"]
    invitation = db_client.post(
        f"/api/projects/{project_id}/invitations",
        headers=_auth(instructor_token),
        json={"email": member_email, "role": "viewer"},
    )
    assert invitation.status_code == 201
    accepted = db_client.post(
        f"/api/projects/invitations/{invitation.json()['id']}/accept",
        headers=_auth(member_token),
    )
    assert accepted.status_code == 200
    return project_id, member


def test_student_cannot_create_invitation(
    db_client: Any, provision_user: Any
) -> None:
    """Students cannot create invitations even for their own project."""
    _, token = provision_user("solo-student@example.com", role="student")
    provision_user("friend@example.com", role="student")
    project_id = db_client.get("/api/projects", headers=_auth(token)).json()[0]["id"]

    response = db_client.post(
        f"/api/projects/{project_id}/invitations",
        headers=_auth(token),
        json={"email": "friend@example.com", "role": "viewer"},
    )

    assert response.status_code == 403


def test_instructor_can_invite_to_project_they_do_not_own(
    db_client: Any, provision_user: Any
) -> None:
    """Instructors may invite into a project owned by someone else."""
    _, owner_token = provision_user("team-owner@example.com", role="student")
    _, instructor_token = provision_user(
        "team-instructor@example.com", role="instructor"
    )
    provision_user("add-me@example.com", role="student")
    project_id = db_client.get(
        "/api/projects", headers=_auth(owner_token)
    ).json()[0]["id"]

    response = db_client.post(
        f"/api/projects/{project_id}/invitations",
        headers=_auth(instructor_token),
        json={"email": "add-me@example.com", "role": "viewer"},
    )

    assert response.status_code == 201


def test_instructor_can_list_and_cancel_invitation_for_project_they_do_not_own(
    db_client: Any, provision_user: Any
) -> None:
    """Instructors can list and cancel invitations on a foreign project."""
    _, owner_token = provision_user("list-owner@example.com", role="student")
    _, instructor_token = provision_user(
        "list-instructor@example.com", role="instructor"
    )
    provision_user("list-invitee@example.com", role="student")
    project_id = db_client.get(
        "/api/projects", headers=_auth(owner_token)
    ).json()[0]["id"]
    invitation = db_client.post(
        f"/api/projects/{project_id}/invitations",
        headers=_auth(instructor_token),
        json={"email": "list-invitee@example.com", "role": "viewer"},
    )
    assert invitation.status_code == 201
    invitation_id = invitation.json()["id"]

    listed = db_client.get(
        f"/api/projects/{project_id}/invitations",
        headers=_auth(instructor_token),
    )
    cancelled = db_client.delete(
        f"/api/projects/{project_id}/invitations/{invitation_id}",
        headers=_auth(instructor_token),
    )

    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [invitation_id]
    assert cancelled.status_code == 204


def test_student_owner_cannot_patch_member_role(
    db_client: Any, provision_user: Any
) -> None:
    """A student owner gets 403 when patching a member's role."""
    _, owner_token = provision_user("patch-owner@example.com", role="student")
    _, instructor_token = provision_user(
        "patch-instructor@example.com", role="instructor"
    )
    member, member_token = provision_user("patch-member@example.com", role="student")
    project_id = db_client.get(
        "/api/projects", headers=_auth(owner_token)
    ).json()[0]["id"]
    invitation = db_client.post(
        f"/api/projects/{project_id}/invitations",
        headers=_auth(instructor_token),
        json={"email": member.email, "role": "viewer"},
    )
    assert invitation.status_code == 201
    accepted = db_client.post(
        f"/api/projects/invitations/{invitation.json()['id']}/accept",
        headers=_auth(member_token),
    )
    assert accepted.status_code == 200

    response = db_client.patch(
        f"/api/projects/{project_id}/members/{member.id}",
        headers=_auth(owner_token),
        json={"role": "operator"},
    )

    assert response.status_code == 403


def test_instructor_can_patch_member_role_for_project_they_do_not_own(
    db_client: Any, provision_user: Any
) -> None:
    """Instructors can patch member roles on a project they do not own."""
    _, owner_token = provision_user("staff-patch-owner@example.com", role="student")
    _, instructor_token = provision_user(
        "staff-patch-instructor@example.com", role="instructor"
    )
    member, member_token = provision_user(
        "staff-patch-member@example.com", role="student"
    )
    project_id = db_client.get(
        "/api/projects", headers=_auth(owner_token)
    ).json()[0]["id"]
    invitation = db_client.post(
        f"/api/projects/{project_id}/invitations",
        headers=_auth(instructor_token),
        json={"email": member.email, "role": "viewer"},
    )
    assert invitation.status_code == 201
    accepted = db_client.post(
        f"/api/projects/invitations/{invitation.json()['id']}/accept",
        headers=_auth(member_token),
    )
    assert accepted.status_code == 200

    response = db_client.patch(
        f"/api/projects/{project_id}/members/{member.id}",
        headers=_auth(instructor_token),
        json={"role": "operator"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "operator"


def test_student_owner_cannot_remove_member(
    db_client: Any, provision_user: Any
) -> None:
    """A student owner gets 403 when removing a member."""
    _, owner_token = provision_user("remove-owner@example.com", role="student")
    _, instructor_token = provision_user(
        "remove-instructor@example.com", role="instructor"
    )
    project_id, member = _invite_and_accept_member(
        db_client,
        provision_user,
        owner_token=owner_token,
        instructor_token=instructor_token,
        member_email="remove-member@example.com",
    )

    response = db_client.delete(
        f"/api/projects/{project_id}/members/{member.id}",
        headers=_auth(owner_token),
    )

    assert response.status_code == 403


def test_instructor_can_remove_member_for_project_they_do_not_own(
    db_client: Any, provision_user: Any
) -> None:
    """Instructors can remove members from a project they do not own."""
    _, owner_token = provision_user("staff-remove-owner@example.com", role="student")
    _, instructor_token = provision_user(
        "staff-remove-instructor@example.com", role="instructor"
    )
    project_id, member = _invite_and_accept_member(
        db_client,
        provision_user,
        owner_token=owner_token,
        instructor_token=instructor_token,
        member_email="staff-remove-member@example.com",
    )

    response = db_client.delete(
        f"/api/projects/{project_id}/members/{member.id}",
        headers=_auth(instructor_token),
    )
    members = db_client.get(
        f"/api/projects/{project_id}/members", headers=_auth(owner_token)
    )

    assert response.status_code == 204
    assert str(member.id) not in {row["user_id"] for row in members.json()}


def test_instructor_cannot_remove_sole_project_owner(
    db_client: Any, provision_user: Any
) -> None:
    """Instructors get 403 when trying to remove a project's sole owner."""
    owner, owner_token = provision_user("sole-owner@example.com", role="student")
    _, instructor_token = provision_user(
        "sole-owner-instructor@example.com", role="instructor"
    )
    project_id = db_client.get(
        "/api/projects", headers=_auth(owner_token)
    ).json()[0]["id"]

    response = db_client.delete(
        f"/api/projects/{project_id}/members/{owner.id}",
        headers=_auth(instructor_token),
    )

    assert response.status_code == 403


def test_instructor_cannot_remove_self_from_personal_project(
    db_client: Any, provision_user: Any
) -> None:
    """Instructors cannot remove themselves from their personal project."""
    instructor, instructor_token = provision_user(
        "personal-owner@example.com", role="instructor"
    )
    project_id = db_client.get(
        "/api/projects", headers=_auth(instructor_token)
    ).json()[0]["id"]

    response = db_client.delete(
        f"/api/projects/{project_id}/members/{instructor.id}",
        headers=_auth(instructor_token),
    )

    assert response.status_code == 403
