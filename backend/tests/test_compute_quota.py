from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.containers.docker_orchestrator import VELA_PROJECT_LABEL
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus, HealthStatus
from app.core.exceptions import TeamComputeQuotaExceededError
from app.core.models import ContainerInfo, DeployConfig
from app.core.quotas.compute_quota import (
    _effective_limits,
    enforce_team_compute_capacity,
    environment_compute_ceilings,
    team_compute_usage,
)
from app.db.base import Base
from app.db.models import DeploymentRecord, Organization, Project, User


@pytest_asyncio.fixture
async def quota_db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _info(project_id: uuid.UUID, container_id: str) -> ContainerInfo:
    return ContainerInfo(
        id=container_id,
        name="web",
        image="nginx",
        status=ContainerStatus.RUNNING,
        health=HealthStatus.HEALTHY,
        ports=[],
        labels={VELA_PROJECT_LABEL: str(project_id)},
        access_url=None,
        access_role=None,
        source_kind=None,
        source_label=None,
        created_at=datetime.now(UTC),
    )


async def _seed(session: AsyncSession, *, max_running: int | None = None) -> tuple[Project, str]:
    organization = Organization(name="compute org")
    session.add(organization)
    await session.flush()
    project = Project(
        organization_id=organization.id,
        name="Compute team",
        max_running_containers=max_running,
    )
    user = User(id=uuid.uuid4(), email="compute@example.com")
    session.add_all([project, user])
    await session.flush()
    container_id = "container-a"
    config = DeployConfig(
        image="nginx", name="web", cpu_limit=0.5, memory_limit=512, project_id=project.id,
    )
    session.add(DeploymentRecord(
        user_id=user.id,
        project_id=project.id,
        container_id=container_id,
        container_name="web",
        source_kind="image",
        source_ref="nginx",
        image_tag="nginx:latest",
        container_port=80,
        deploy_config=config.model_dump(mode="json"),
    ))
    await session.commit()
    return project, container_id


def test_ceilings_parse_and_clamp(monkeypatch) -> None:
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "10")
    monkeypatch.setenv("VELA_TEAM_MAX_CPU_MILLICORES", "4000")
    monkeypatch.setenv("VELA_TEAM_MAX_MEMORY_BYTES", "")
    monkeypatch.setenv("VELA_TEAM_MAX_DEPLOYS_PER_HOUR", "0")
    assert environment_compute_ceilings() == {
        "running_containers": 10,
        "cpu_millicores": 4000,
        "memory_bytes": None,
        "deploys_per_hour": None,
    }


def test_effective_limits_falls_back_to_platform_ceiling(monkeypatch) -> None:
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "20")
    project = Project(name="ceiling team", organization_id=uuid.uuid4())
    assert _effective_limits(project)["running_containers"] == 20


@pytest.mark.asyncio
async def test_usage_converts_cores_and_mb(
    quota_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, container_id = await _seed(quota_db)
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "")
    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(_info(project.id, container_id))
    usage = await team_compute_usage(quota_db, orchestrator, project.id)
    assert usage.running_containers == 1
    assert usage.cpu_millicores == 500
    assert usage.memory_bytes == 512 * 1024**2


@pytest.mark.asyncio
async def test_enforcement_raises_when_over_quota(quota_db: AsyncSession) -> None:
    project, container_id = await _seed(quota_db, max_running=1)
    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(_info(project.id, container_id))
    with pytest.raises(TeamComputeQuotaExceededError) as excinfo:
        await enforce_team_compute_capacity(quota_db, orchestrator, project.id)
    assert "running containers" in str(excinfo.value)
