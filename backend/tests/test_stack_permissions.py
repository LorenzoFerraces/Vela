"""Integration tests for stack RBAC and deploy rollback."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from tests.test_project_container_access import _invite_and_accept, _register


def _create_stack(client: TestClient, *, name: str, project_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "services": [
            {
                "service_name": "web",
                "source_kind": "image",
                "source_ref": "nginx:alpine",
                "container_port": 80,
                "env_vars": {},
                "public_route": False,
            }
        ],
    }
    if project_id is not None:
        body["project_id"] = project_id
    response = client.post("/api/stacks/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_viewer_cannot_import_or_deploy_stack(integration_app: Any) -> None:
    with TestClient(integration_app) as owner_client, TestClient(integration_app) as viewer_client:
        _, project_id, _ = _register(owner_client, "stack-owner@example.com")
        _register(viewer_client, "stack-viewer@example.com")
        _invite_and_accept(
            owner_client,
            viewer_client,
            project_id=project_id,
            invitee_email="stack-viewer@example.com",
            role="viewer",
        )

        stack = _create_stack(owner_client, name="rbac-stack", project_id=project_id)

        import_denied = viewer_client.post(
            "/api/stacks/import-compose",
            json={
                "project_id": project_id,
                "name": "viewer-import",
                "yaml_content": "services:\n  web:\n    image: nginx:alpine\n",
            },
        )
        assert import_denied.status_code == 403

        deploy_denied = viewer_client.post(f"/api/stacks/{stack['id']}/deploy")
        assert deploy_denied.status_code == 403

        create_denied = viewer_client.post(
            "/api/stacks/",
            json={
                "project_id": project_id,
                "name": "viewer-create",
                "services": [
                    {
                        "service_name": "web",
                        "source_kind": "image",
                        "source_ref": "nginx:alpine",
                        "container_port": 80,
                        "env_vars": {},
                        "public_route": False,
                    }
                ],
            },
        )
        assert create_denied.status_code == 403


def test_stack_partial_deploy_rolls_back(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
) -> None:
    fake_orchestrator.fail_deploy_for_image("python:3.12-slim")

    created = api_client.post(
        "/api/stacks/",
        json={
            "name": "rollback-stack",
            "services": [
                {
                    "service_name": "web",
                    "source_kind": "image",
                    "source_ref": "nginx:alpine",
                    "container_port": 80,
                    "env_vars": {},
                    "public_route": False,
                },
                {
                    "service_name": "api",
                    "source_kind": "image",
                    "source_ref": "python:3.12-slim",
                    "container_port": 8000,
                    "env_vars": {},
                    "public_route": False,
                    "depends_on": ["web"],
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    stack_id = created.json()["id"]
    network_name = created.json()["network_name"]

    deployed = api_client.post(f"/api/stacks/{stack_id}/deploy")
    assert deployed.status_code == 500
    assert "api" in deployed.json()["detail"]

    assert network_name not in fake_orchestrator._networks
    remaining = [
        container
        for container in fake_orchestrator._containers.values()
        if container.name.startswith("rollback-stack_")
    ]
    assert remaining == []

    api_client.delete(f"/api/stacks/{stack_id}")
