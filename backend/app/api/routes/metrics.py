"""Metrics time-series API."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_orchestrator
from app.api.schemas import (
    ContainerUsageEntry,
    MetricPoint,
    MetricSummary,
    ProjectUsage,
    UsageSummary,
)
from app.core.containers.docker_orchestrator import (
    VELA_PROJECT_LABEL,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.enums import ContainerStatus
from app.core.projects.access import (
    list_accessible_project_ids,
    require_container_access,
)
from app.core.quotas import (
    effective_quota_bytes,
    usage_from_containers,
)
from app.core.models import ContainerInfo
from app.db.models import (
    ContainerMetric,
    Organization,
    Project,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _metric_point(row: ContainerMetric) -> MetricPoint:
    return MetricPoint(
        timestamp=row.timestamp,
        cpu_percent=row.cpu_percent,
        memory_usage_bytes=row.memory_usage_bytes,
        memory_limit_bytes=row.memory_limit_bytes,
        memory_percent=row.memory_percent,
        network_rx_bytes=row.network_rx_bytes,
        network_tx_bytes=row.network_tx_bytes,
    )


def _aware(ts: datetime) -> datetime:
    # SQLite reads back naive UTC; Postgres returns aware datetimes.
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


async def _rows_since(
    session: AsyncSession, container_id: str, hours: int
) -> list[ContainerMetric]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(ContainerMetric)
        .where(
            ContainerMetric.container_id == container_id,
            ContainerMetric.timestamp >= since,
        )
        .order_by(ContainerMetric.timestamp.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("")
async def get_metrics(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    container_id: str,
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[MetricPoint]:
    """Return the newest stored metric points for a container, in time order."""
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )
    rows = await _rows_since(session, container_id, hours)
    newest_first = list(reversed(rows))[:limit]
    return [_metric_point(row) for row in reversed(newest_first)]


@router.get("/summary")
async def get_metrics_summary(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    container_id: str,
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
) -> list[MetricSummary]:
    """Return aggregated metric summaries grouped by 1-hour buckets."""
    await require_container_access(
        session, orchestrator, current_user, container_id, action="read"
    )
    rows = await _rows_since(session, container_id, hours)

    buckets: dict[datetime, list[ContainerMetric]] = {}
    for row in rows:
        bucket_start = _aware(row.timestamp).replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(bucket_start, []).append(row)

    return [
        MetricSummary(
            bucket_start=bucket_start,
            cpu_avg=round(sum(r.cpu_percent for r in bucket) / len(bucket), 2),
            cpu_max=round(max(r.cpu_percent for r in bucket), 2),
            cpu_min=round(min(r.cpu_percent for r in bucket), 2),
            memory_usage_avg=int(sum(r.memory_usage_bytes for r in bucket) / len(bucket)),
            memory_usage_max=max(r.memory_usage_bytes for r in bucket),
            memory_limit_avg=int(sum(r.memory_limit_bytes for r in bucket) / len(bucket)),
            memory_percent_avg=round(sum(r.memory_percent for r in bucket) / len(bucket), 2),
            memory_percent_max=round(max(r.memory_percent for r in bucket), 2),
            network_rx_total=sum(r.network_rx_bytes for r in bucket),
            network_tx_total=sum(r.network_tx_bytes for r in bucket),
        )
        for bucket_start, bucket in sorted(buckets.items())
    ]


@router.get("/usage", response_model=UsageSummary)
async def get_usage(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> UsageSummary:
    """Latest resource usage for every container the caller can access.

    Grouped by project (team or personal) so users and team members can see
    what each team's workloads consume. Only running containers report usage;
    their stored rows for stopped containers would be stale.
    """
    project_ids = await list_accessible_project_ids(session, current_user.id)
    containers = await orchestrator.list(
        project_ids=project_ids, user_id=current_user.id
    )
    if not containers:
        return UsageSummary(
            projects=[],
            total_cpu_percent=0.0,
            total_memory_usage_bytes=0,
            running_containers=0,
        )

    latest = await latest_metric_by_container(session, [c.id for c in containers])
    projects = (
        (await session.execute(select(Project).where(Project.id.in_(project_ids))))
        .scalars()
        .all()
    )
    project_by_id = {p.id: p for p in projects}
    orgs = (
        (
            await session.execute(
                select(Organization).where(
                    Organization.id.in_({p.organization_id for p in projects})
                )
            )
        )
        .scalars()
        .all()
    )
    org_by_id = {o.id: o for o in orgs}

    grouped: dict[uuid.UUID | None, list[ContainerInfo]] = {}
    for info in containers:
        raw_project_id = info.labels.get(VELA_PROJECT_LABEL)
        try:
            project_id: uuid.UUID | None = (
                uuid.UUID(raw_project_id) if raw_project_id else None
            )
        except ValueError:
            project_id = None
        grouped.setdefault(project_id, []).append(info)

    project_usages: list[ProjectUsage] = []
    total_cpu = 0.0
    total_memory = 0
    running = 0
    for project_id, members in grouped.items():
        project = project_by_id.get(project_id) if project_id else None
        # Unlabeled containers are the caller's own; quota checks attribute
        # their storage to the caller's personal project.
        storage_project = project
        if storage_project is None:
            storage_project = (
                project_by_id.get(current_user.personal_project_id)
                if current_user.personal_project_id is not None
                else None
            )
        entries: list[ContainerUsageEntry] = []
        for info in members:
            is_running = info.status == ContainerStatus.RUNNING
            row = latest.get(info.id) if is_running else None
            if row is not None:
                total_cpu += row.cpu_percent
                total_memory += row.memory_usage_bytes
            if is_running:
                running += 1
            entries.append(
                ContainerUsageEntry(
                    container_id=info.id,
                    name=info.name,
                    status=info.status.value,
                    project_id=project_id,
                    project_name=project.name if project else None,
                    team_name=(
                        org_by_id[project.organization_id].name
                        if project is not None and project.organization_id in org_by_id
                        else None
                    ),
                    cpu_percent=row.cpu_percent if row else None,
                    memory_usage_bytes=row.memory_usage_bytes if row else None,
                    memory_percent=row.memory_percent if row else None,
                )
            )
        if storage_project is not None:
            disk_bytes, uploads_bytes = await usage_from_containers(
                session, containers, storage_project.id
            )
            storage_used_bytes = disk_bytes + uploads_bytes
            storage_quota_bytes = effective_quota_bytes(storage_project)
        else:
            storage_used_bytes = 0
            storage_quota_bytes = None
        project_usages.append(
            ProjectUsage(
                project_id=project_id,
                project_name=project.name if project else None,
                team_name=(
                    org_by_id[project.organization_id].name
                    if project is not None and project.organization_id in org_by_id
                    else None
                ),
                cpu_percent_total=round(
                    sum(e.cpu_percent or 0.0 for e in entries), 2
                ),
                memory_usage_bytes_total=sum(
                    e.memory_usage_bytes or 0 for e in entries
                ),
                storage_quota_bytes=storage_quota_bytes,
                storage_used_bytes=storage_used_bytes,
                storage_over_quota=(
                    storage_quota_bytes is not None
                    and storage_used_bytes >= storage_quota_bytes
                ),
                containers=entries,
            )
        )
    project_usages.sort(key=lambda p: p.memory_usage_bytes_total, reverse=True)

    return UsageSummary(
        projects=project_usages,
        total_cpu_percent=round(total_cpu, 2),
        total_memory_usage_bytes=total_memory,
        running_containers=running,
    )


async def latest_metric_by_container(
    session: AsyncSession, container_ids: list[str]
) -> dict[str, ContainerMetric]:
    """Latest stored row per container (empty dict-safe, dialect-safe)."""
    if not container_ids:
        return {}
    subq = (
        select(
            ContainerMetric.container_id,
            func.max(ContainerMetric.timestamp).label("latest_ts"),
        )
        .where(ContainerMetric.container_id.in_(container_ids))
        .group_by(ContainerMetric.container_id)
        .subquery()
    )
    stmt = select(ContainerMetric).join(
        subq,
        (ContainerMetric.container_id == subq.c.container_id)
        & (ContainerMetric.timestamp == subq.c.latest_ts),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {row.container_id: row for row in rows}
