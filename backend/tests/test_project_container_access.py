"""Integration tests for project-scoped container RBAC."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient

from app.core.containers.docker_orchestrator import VELA_PROJECT_LABEL
from tests.conftest import make_container_info


def _register(client: TestClient, email: str) -> tuple[str, str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password-min-8-chars"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    token = body["access_token"]
    user_id = body["user"]["id"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    projects = client.get("/api/projects/").json()
    return token, projects[0]["id"], user_id


def _invite_and_accept(
    owner_client: TestClient,
    invitee_client: TestClient,
    *,
    project_id: str,
    invitee_email: str,
    role: str,
) -> None:
    invitation = owner_client.post(
        f"/api/projects/{project_id}/invitations",
        json={"email": invitee_email, "role": role},
    )
    assert invitation.status_code == 201, invitation.text
    incoming = invitee_client.get("/api/projects/invitations/incoming").json()
    invitation_id = next(
        row["id"] for row in incoming if row["project_id"] == project_id
    )
    accepted = invitee_client.post(
        f"/api/projects/invitations/{invitation_id}/accept",
    )
    assert accepted.status_code == 200, accepted.text


def test_pending_invite_has_no_container_access(
    integration_app: Any,
    fake_orchestrator: Any,
) -> None:
    with TestClient(integration_app) as owner_client, TestClient(integration_app) as invitee_client:
        _, project_id, owner_user_id = _register(owner_client, "rbac-owner@example.com")
        _register(invitee_client, "rbac-invitee@example.com")

        pending = owner_client.post(
            f"/api/projects/{project_id}/invitations",
            json={"email": "rbac-invitee@example.com", "role": "viewer"},
        )
        assert pending.status_code == 201

        shared_container = make_container_info(
            owner_id=owner_user_id,
            id="shared-cid",
            labels={VELA_PROJECT_LABEL: project_id},
        )
        fake_orchestrator.seed_container(shared_container)

        list_before = invitee_client.get("/api/containers/")
        assert list_before.status_code == 200
        assert list_before.json() == []

        get_response = invitee_client.get("/api/containers/shared-cid")
        assert get_response.status_code == 404


def test_viewer_can_read_but_not_stop(
    integration_app: Any,
    fake_orchestrator: Any,
) -> None:
    with TestClient(integration_app) as owner_client, TestClient(integration_app) as invitee_client:
        _, project_id, owner_user_id = _register(owner_client, "viewer-owner@example.com")
        _register(invitee_client, "viewer-member@example.com")
        _invite_and_accept(
            owner_client,
            invitee_client,
            project_id=project_id,
            invitee_email="viewer-member@example.com",
            role="viewer",
        )

        shared_container = make_container_info(
            owner_id=owner_user_id,
            id="viewer-cid",
            labels={VELA_PROJECT_LABEL: project_id},
        )
        fake_orchestrator.seed_container(shared_container)

        listed = invitee_client.get("/api/containers/")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["access_role"] == "viewer"

        stop_response = invitee_client.post("/api/containers/viewer-cid/stop")
        assert stop_response.status_code == 403


def test_operator_can_stop_shared_container(
    integration_app: Any,
    fake_orchestrator: Any,
) -> None:
    with TestClient(integration_app) as owner_client, TestClient(integration_app) as invitee_client:
        _, project_id, owner_user_id = _register(owner_client, "operator-owner@example.com")
        _register(invitee_client, "operator-member@example.com")
        _invite_and_accept(
            owner_client,
            invitee_client,
            project_id=project_id,
            invitee_email="operator-member@example.com",
            role="operator",
        )

        shared_container = make_container_info(
            owner_id=owner_user_id,
            id="operator-cid",
            labels={VELA_PROJECT_LABEL: project_id},
        )
        fake_orchestrator.seed_container(shared_container)

        stop_response = invitee_client.post("/api/containers/operator-cid/stop")
        assert stop_response.status_code == 200


def test_outsider_cannot_see_shared_container(
    integration_app: Any,
    fake_orchestrator: Any,
) -> None:
    with (
        TestClient(integration_app) as owner_client,
        TestClient(integration_app) as stranger_client,
    ):
        _, project_id, owner_user_id = _register(owner_client, "outsider-owner@example.com")
        _register(stranger_client, "outsider-stranger@example.com")

        shared_container = make_container_info(
            owner_id=owner_user_id,
            id="outsider-cid",
            labels={VELA_PROJECT_LABEL: project_id},
        )
        fake_orchestrator.seed_container(shared_container)

        listed = stranger_client.get("/api/containers/")
        assert listed.status_code == 200
        assert listed.json() == []

        get_response = stranger_client.get("/api/containers/outsider-cid")
        assert get_response.status_code == 404
