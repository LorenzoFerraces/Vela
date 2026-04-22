"""Fixtures for pytest API integration tests (mocked orchestrator / builder / traffic)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.deps import get_image_builder, get_orchestrator, get_traffic_router
from app.api.app import create_app
from app.core.default_image_builder import DefaultImageBuilder
from app.core.enums import BuildStrategy, ContainerStatus, HealthStatus, SupportedLanguage
from app.core.models import BuildResult, ContainerInfo, ContainerStats, HealthResult, ProjectInfo
from app.core.orchestrator import ContainerOrchestrator
from app.core.traffic_router import NoopTrafficRouter


def make_container_info(**overrides: object) -> ContainerInfo:
    data: dict[str, object] = {
        "id": "cid-1",
        "name": "vela-test",
        "image": "nginx:alpine",
        "status": ContainerStatus.RUNNING,
        "created_at": datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
        "ports": [],
        "labels": {},
        "health": HealthStatus.NONE,
    }
    data.update(overrides)
    return ContainerInfo.model_validate(data)


@pytest.fixture
def sample_container() -> ContainerInfo:
    return make_container_info()


@pytest.fixture
def mock_orchestrator(sample_container: ContainerInfo) -> MagicMock:
    orch = MagicMock(spec=ContainerOrchestrator)
    orch.deploy = AsyncMock(return_value=sample_container)
    orch.start = AsyncMock(return_value=sample_container)
    orch.stop = AsyncMock(return_value=sample_container)
    orch.restart = AsyncMock(return_value=sample_container)
    orch.remove = AsyncMock(return_value=None)
    orch.get = AsyncMock(return_value=sample_container)
    orch.list = AsyncMock(return_value=[sample_container])
    orch.logs = AsyncMock(return_value="log line\n")
    orch.pull_image = AsyncMock(return_value=None)
    orch.build_image = AsyncMock(return_value="sha256:deadbeef")
    orch.list_images = AsyncMock(return_value=["nginx:alpine"])
    orch.verify_image_reference_available = AsyncMock(return_value=None)

    orch.get_stats = AsyncMock(
        return_value=ContainerStats(
            container_id=sample_container.id,
            timestamp=datetime.now(timezone.utc),
            cpu_percent=1.0,
            memory_usage_bytes=1000,
            memory_limit_bytes=2000,
            memory_percent=50.0,
        )
    )
    orch.get_health = AsyncMock(
        return_value=HealthResult(
            status=HealthStatus.HEALTHY,
            timestamp=datetime.now(timezone.utc),
        )
    )
    return orch


@pytest.fixture
def noop_router() -> NoopTrafficRouter:
    return NoopTrafficRouter()


@pytest.fixture
def mock_image_builder(mock_orchestrator: MagicMock) -> MagicMock:
    builder = MagicMock(spec=DefaultImageBuilder)
    builder.build_from_source = AsyncMock(
        return_value=BuildResult(
            image_id="sha256:built",
            image_tag="vela/gitbuild:abc123",
            strategy=BuildStrategy.DOCKERFILE_EXISTS,
            build_log="",
            project_info=ProjectInfo(language=SupportedLanguage.PYTHON, has_dockerfile=True),
        )
    )
    builder.analyze = AsyncMock(
        return_value=ProjectInfo(language=SupportedLanguage.PYTHON, has_dockerfile=False)
    )
    return builder


@pytest.fixture
def api_client(
    mock_orchestrator: MagicMock,
    mock_image_builder: MagicMock,
    noop_router: NoopTrafficRouter,
):
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_traffic_router] = lambda: noop_router
    app.dependency_overrides[get_image_builder] = lambda: mock_image_builder

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
