"""Viewer stack deletes must be rejected before any Docker state is mutated."""

from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.auth.tokens import create_access_token
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.models import ContainerInfo, ContainerStatus
from app.db.models import ProjectMembership, Stack, User


def test_viewer_delete_stack_is_403_and_docker_state_intact(
    api_client: TestClient,
    other_user_client: TestClient,
    seeded_user: User,
    seeded_other_user: User,
    fake_orchestrator: FakeContainerOrchestrator,
    db_session_factory,
) -> None:
    async def make_viewer() -> None:
        async with db_session_factory() as session:
            session.add(ProjectMembership(
                project_id=seeded_user.personal_project_id,
                user_id=seeded_other_user.id,
                role="viewer",
            ))
            await session.commit()

    asyncio.run(make_viewer())

    created = api_client.post("/api/stacks/", json={
        "name": "guarded",
        "services": [{
            "service_name": "web", "source_kind": "image", "source_ref": "nginx:alpine",
            "container_port": 80, "public_route": False,
        }],
    })
    assert created.status_code == 201
    body = created.json()
    stack_id = uuid.UUID(body["id"])

    info = ContainerInfo.model_validate({
        "id": "stack-cid-1", "name": "guarded_web", "image": "nginx:alpine",
        "status": ContainerStatus.RUNNING,
        "created_at": "2026-04-01T12:00:00+00:00", "labels": {}, "ports": [],
    })
    fake_orchestrator.seed_container(info)
    network_name = body["network_name"]
    asyncio.run(fake_orchestrator.create_network(network_name))

    other_user_client.headers["Authorization"] = f"Bearer {create_access_token(seeded_other_user.id)}"
    response = other_user_client.delete(f"/api/stacks/{stack_id}")
    assert response.status_code == 403

    assert "guarded_web" in [c.name for c in asyncio.run(fake_orchestrator.list())]
    assert network_name in fake_orchestrator._networks

    async def stack_exists() -> bool:
        async with db_session_factory() as session:
            result = await session.execute(select(Stack).where(Stack.id == stack_id))
            return result.scalar_one_or_none() is not None

    assert asyncio.run(stack_exists())
