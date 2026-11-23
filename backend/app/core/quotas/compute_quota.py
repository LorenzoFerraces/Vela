from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.docker_orchestrator import (
    VELA_PROJECT_LABEL,
    VELA_REPLICA_OF_LABEL,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.deploy.deployment_history import load_deploy_config_snapshot
from app.core.exceptions import TeamComputeQuotaExceededError
from app.core.models import DeployConfig
from app.db.models import DeploymentRecord, Project


@dataclass(frozen=True)
class ComputeQuotaUsage:
    running_containers: int
    cpu_millicores: int
    memory_bytes: int
    deploys_per_hour: int


@dataclass(frozen=True)
class ComputeQuotaSummary:
    usage: ComputeQuotaUsage
    ceilings: dict[str, int | None]
    limits: dict[str, int | None]
    over_quota: dict[str, bool]


def _positive_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def environment_compute_ceilings() -> dict[str, int | None]:
    return {
        "running_containers": _positive_env("VELA_TEAM_MAX_RUNNING_CONTAINERS"),
        "cpu_millicores": _positive_env("VELA_TEAM_MAX_CPU_MILLICORES"),
        "memory_bytes": _positive_env("VELA_TEAM_MAX_MEMORY_BYTES"),
        "deploys_per_hour": _positive_env("VELA_TEAM_MAX_DEPLOYS_PER_HOUR"),
    }


def _effective_limits(project: Project) -> dict[str, int | None]:
    ceilings = environment_compute_ceilings()
    stored = {
        "running_containers": project.max_running_containers,
        "cpu_millicores": project.max_cpu_millicores,
        "memory_bytes": project.max_memory_bytes,
        "deploys_per_hour": project.max_deploys_per_hour,
    }
    limits: dict[str, int | None] = {}
    for key, value in stored.items():
        ceiling = ceilings[key]
        if value is None:
            limits[key] = ceiling
        elif ceiling is None:
            limits[key] = value
        else:
            limits[key] = min(value, ceiling)
    return limits


async def team_compute_usage(
    session: AsyncSession, orchestrator: ContainerOrchestrator, project_id: uuid.UUID,
) -> ComputeQuotaUsage:
    # Mirror usage_from_containers (storage_quota.py): orchestrator.list(project_ids=...)
    # only filters when user_id is also set, so list once and filter by label in Python.
    containers = await orchestrator.list()
    running = [
        info for info in containers
        if info.labels.get(VELA_PROJECT_LABEL) == str(project_id) and info.status == "running"
    ]
    cpu_millicores = 0
    memory_bytes = 0
    containers_by_name = {info.name: info for info in containers}
    base_snapshots: dict[str, DeployConfig | None] = {}
    for info in running:
        config = await load_deploy_config_snapshot(session, info.id)
        if config is None:
            # Replicas have no DeploymentRecord of their own; their limits come
            # from the base config used to create them.
            base_name = info.labels.get(VELA_REPLICA_OF_LABEL)
            if not base_name:
                continue
            if base_name not in base_snapshots:
                base_info = containers_by_name.get(base_name)
                base_snapshots[base_name] = (
                    await load_deploy_config_snapshot(session, base_info.id)
                    if base_info is not None
                    else None
                )
            config = base_snapshots[base_name]
        if config is None:
            continue
        cpu_millicores += int((config.cpu_limit or 0.0) * 1000)
        memory_bytes += (config.memory_limit or 0) * 1024**2
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    deploys = (await session.execute(
        select(func.count(DeploymentRecord.id)).where(
            DeploymentRecord.project_id == project_id,
            DeploymentRecord.created_at >= since,
        )
    )).scalar_one()
    return ComputeQuotaUsage(len(running), cpu_millicores, memory_bytes, int(deploys))


async def enforce_team_compute_capacity(
    session: AsyncSession, orchestrator: ContainerOrchestrator, project_id: uuid.UUID,
    *, pending: DeployConfig | None = None,
) -> None:
    project = await session.get(Project, project_id)
    if project is None:
        return
    limits = _effective_limits(project)
    usage = await team_compute_usage(session, orchestrator, project_id)
    projected = {
        "running_containers": usage.running_containers + (1 if pending else 0),
        "cpu_millicores": usage.cpu_millicores + (
            int((pending.cpu_limit or 0.0) * 1000) if pending else 0
        ),
        "memory_bytes": usage.memory_bytes + (
            (pending.memory_limit or 0) * 1024**2 if pending else 0
        ),
        "deploys_per_hour": usage.deploys_per_hour,
    }
    for key in ("running_containers", "cpu_millicores", "memory_bytes", "deploys_per_hour"):
        limit = limits[key]
        used = projected[key]
        if limit is not None and used >= limit:
            raise TeamComputeQuotaExceededError(
                f"Team compute quota exceeded for {key.replace('_', ' ')}: {used} used, limit {limit}"
            )


async def team_compute_quota_summary(
    session: AsyncSession, orchestrator: ContainerOrchestrator, project: Project,
) -> ComputeQuotaSummary:
    usage = await team_compute_usage(session, orchestrator, project.id)
    ceilings = environment_compute_ceilings()
    limits = _effective_limits(project)
    return ComputeQuotaSummary(
        usage=usage,
        ceilings=ceilings,
        limits=limits,
        over_quota={key: limits[key] is not None and getattr(usage, key) >= limits[key] for key in limits},
    )
