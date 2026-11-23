"""Best-effort failure notifications during stack deploy rollback."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import ContainerStatus
from app.core.models import ContainerInfo
from app.core.stacks import repository as stack_repository
from app.core.stacks.deploy import deploy_stack
from app.db.models import Stack, StackService, User


def test_failing_rollback_callbacks_do_not_skip_cleanup_or_mask_error(monkeypatch) -> None:
    stack = Stack(
        id=uuid.uuid4(), name="web", network_name="vela-stack-rollback",
        project_id=uuid.uuid4(),
    )
    user = User(id=uuid.uuid4(), email="rollback@example.com")
    services = [
        StackService(
            service_name=name, source_kind="image", source_ref="nginx:latest",
            git_branch=None, container_port=80, env_vars={}, command=None,
            public_route=False, depends_on=None, volumes=[],
        )
        for name in ("web", "api")
    ]
    monkeypatch.setattr(
        stack_repository, "resolve_composition", lambda *_args: services
    )

    first = ContainerInfo(
        id="container-web", name="web_web", image="nginx",
        status=ContainerStatus.RUNNING, created_at=datetime.now(UTC),
    )
    orchestrator = AsyncMock()
    orchestrator.deploy.side_effect = [first, RuntimeError("deploy boom")]
    router = AsyncMock()
    builder = AsyncMock()

    async def on_phase(phase: str, _detail: str | None) -> None:
        if phase == "rolling_back":
            raise RuntimeError("notification down")

    async def on_service_state(_name: str, state: str) -> None:
        if state == "failed":
            raise RuntimeError("state callback down")

    result = asyncio.run(
        deploy_stack(
            MagicMock(), orchestrator, router, builder, stack, user, [],
            on_phase=on_phase, on_service_state=on_service_state,
        )
    )

    assert result["error"] == "deploy boom"
    assert result["failed_service"] == "api"
    orchestrator.stop.assert_awaited_once_with("container-web", timeout=5)
    orchestrator.remove.assert_awaited_once_with("container-web", force=True)
    orchestrator.remove_network.assert_awaited_once_with(stack.network_name)
