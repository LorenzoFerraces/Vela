"""Team (project) storage quota: measurement, enforcement, over-quota alerts."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.docker_orchestrator import (
    VELA_OWNER_LABEL,
    VELA_PROJECT_LABEL,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.containers.volume_uploads import user_uploads_total_bytes
from app.core.exceptions import TeamStorageQuotaExceededError
from app.core.models import ContainerInfo
from app.core.notifications.email_provider import EmailProvider
from app.db.models import Project, ProjectMembership, User

logger = logging.getLogger(__name__)

GIB = 1024 ** 3

_over_quota_project_ids: set[uuid.UUID] = set()


def format_gib(total_bytes: int) -> str:
    return f"{total_bytes / GIB:.1f} GiB"


def environment_quota_bytes() -> int | None:
    """Platform storage quota from VELA_TEAM_STORAGE_QUOTA_BYTES (None = unlimited)."""
    raw = os.environ.get("VELA_TEAM_STORAGE_QUOTA_BYTES", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid VELA_TEAM_STORAGE_QUOTA_BYTES %r", raw)
        return None
    return value if value > 0 else None


def effective_quota_bytes(project: Project) -> int | None:
    """Team quota, clamped to the platform default (stored can only restrict)."""
    stored = project.storage_quota_bytes
    environment = environment_quota_bytes()
    if stored is None:
        return environment
    if environment is None:
        return stored
    return min(stored, environment)


def quota_source(project: Project) -> str:
    """Where the effective quota comes from: 'team', 'platform', or 'unlimited'."""
    if project.storage_quota_bytes is not None:
        return "team"
    return "platform" if environment_quota_bytes() is not None else "unlimited"


def reset_over_quota_state() -> None:
    _over_quota_project_ids.clear()


def currently_over_quota_projects() -> frozenset[uuid.UUID]:
    return frozenset(_over_quota_project_ids)


async def _member_user_ids(
    session: AsyncSession, project_id: uuid.UUID
) -> list[uuid.UUID]:
    statement = select(ProjectMembership.user_id).where(
        ProjectMembership.project_id == project_id
    )
    return list((await session.execute(statement)).scalars().all())


async def _users_with_personal_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    candidate_user_ids: set[uuid.UUID],
) -> set[uuid.UUID]:
    if not candidate_user_ids:
        return set()
    statement = select(User.id).where(
        User.personal_project_id == project_id,
        User.id.in_(candidate_user_ids),
    )
    return set((await session.execute(statement)).scalars().all())


async def usage_from_containers(
    session: AsyncSession,
    containers: list[ContainerInfo],
    project_id: uuid.UUID,
) -> tuple[int, int]:
    """(container_disk_bytes, uploads_bytes) for one team.

    Container disk counts every container labeled with the project, plus
    project-unlabeled containers whose owner's personal project is this
    project (same fallback as resolve_container_project_id).
    """
    candidate_owners: set[uuid.UUID] = set()
    for container in containers:
        if not container.labels.get(VELA_PROJECT_LABEL):
            raw_owner = container.labels.get(VELA_OWNER_LABEL)
            if raw_owner:
                try:
                    candidate_owners.add(uuid.UUID(raw_owner))
                except ValueError:
                    pass
    personal_owners = await _users_with_personal_project(
        session, project_id, candidate_owners
    )
    labeled = str(project_id)
    disk = sum(
        container.disk_bytes
        for container in containers
        if container.labels.get(VELA_PROJECT_LABEL) == labeled
        or (
            not container.labels.get(VELA_PROJECT_LABEL)
            and str(container.labels.get(VELA_OWNER_LABEL, ""))
            in {str(owner_id) for owner_id in personal_owners}
        )
    )
    member_ids = await _member_user_ids(session, project_id)
    uploads = sum(user_uploads_total_bytes(member_id) for member_id in member_ids)
    return disk, uploads


async def team_storage_usage(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    project_id: uuid.UUID,
) -> tuple[int, int]:
    """(container_disk_bytes, uploads_bytes) currently used by a team."""
    containers = await orchestrator.list()
    return await usage_from_containers(session, containers, project_id)


async def enforce_team_storage_capacity(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    project_id: uuid.UUID,
) -> None:
    """Reject new deployments once the team has reached its storage quota."""
    project = await session.get(Project, project_id)
    if project is None:
        return
    quota = effective_quota_bytes(project)
    if quota is None:
        return
    disk, uploads = await team_storage_usage(session, orchestrator, project_id)
    used = disk + uploads
    if used >= quota:
        raise TeamStorageQuotaExceededError(
            f"This deployment would exceed the {project.name} team's "
            f"{format_gib(quota)} storage quota ({format_gib(used)} used). "
            "Stop or remove containers, or free uploaded folders."
        )


@dataclass(frozen=True)
class TeamStorageQuotaSummary:
    quota_bytes: int | None
    used_bytes: int
    container_disk_bytes: int
    uploads_bytes: int
    over_quota: bool
    source: str


async def team_storage_quota_summary(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    project: Project,
) -> TeamStorageQuotaSummary:
    """Full usage/quota snapshot for a team."""
    quota = effective_quota_bytes(project)
    disk, uploads = await team_storage_usage(session, orchestrator, project.id)
    used = disk + uploads
    return TeamStorageQuotaSummary(
        quota_bytes=quota,
        used_bytes=used,
        container_disk_bytes=disk,
        uploads_bytes=uploads,
        over_quota=quota is not None and used >= quota,
        source=quota_source(project),
    )


async def check_team_storage_quotas(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    email_provider: EmailProvider,
) -> None:
    """Alert members on the rising edge when a team exceeds its storage quota.

    State resets on API restart: a team already over quota re-alarms once
    after a restart (same reset behavior as container state-change alerts).
    """
    from app.core.notifications.alert_service import AlertService

    try:
        containers = await orchestrator.list()
    except Exception:
        logger.warning(
            "Skipping team storage quota check: container list unavailable",
            exc_info=True,
        )
        return
    projects = list((await session.execute(select(Project))).scalars().all())
    for project in projects:
        quota = effective_quota_bytes(project)
        if quota is None:
            _over_quota_project_ids.discard(project.id)
            continue
        disk, uploads = await usage_from_containers(session, containers, project.id)
        used = disk + uploads
        if used >= quota:
            if project.id in _over_quota_project_ids:
                continue
            _over_quota_project_ids.add(project.id)
            member_ids = await _member_user_ids(session, project.id)
            alert_service = AlertService(email_provider, session)
            for member_id in member_ids:
                await alert_service.send_project_storage_alert(
                    user_id=member_id,
                    project_id=project.id,
                    project_name=project.name,
                    used_bytes=used,
                    quota_bytes=quota,
                )
        else:
            _over_quota_project_ids.discard(project.id)
