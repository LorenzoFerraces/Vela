"""PR preview deploy configuration and TTL garbage collection."""

from __future__ import annotations

import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ContainerNotFoundError,
    PreviewSecretForbiddenError,
    RouteNotFoundError,
)
from app.core.models import DeployConfig
from app.core.secret_store import parse_secret_reference
from app.db.models import PreviewDeploy

PREVIEW_CPU_LIMIT_CORES = 0.5
PREVIEW_MEMORY_LIMIT_MB = 512

logger = logging.getLogger(__name__)


def preview_deploy_config(
    *, project_id: uuid.UUID, repo_full_name: str, pr_number: int, head_sha: str,
    image: str, env_vars: dict[str, str], ttl_seconds: int,
) -> DeployConfig:
    for key, value in env_vars.items():
        if parse_secret_reference(value) is not None:
            raise PreviewSecretForbiddenError(f"Secret reference in env key {key!r} is not allowed for previews")
    return DeployConfig(
        image=image,
        name=f"pr-{pr_number}-{head_sha[:8]}-{project_id.hex[:8]}",
        env_vars={"PREVIEW": "true", "PREVIEW_PR": str(pr_number), **env_vars},
        cpu_limit=PREVIEW_CPU_LIMIT_CORES,
        memory_limit=PREVIEW_MEMORY_LIMIT_MB,
        public_route=True,
        labels={"PREVIEW": "true", "PREVIEW_REPO": repo_full_name},
    )


async def collect_expired_previews(
    session: AsyncSession, orchestrator, traffic_router,
) -> int:
    now = datetime.now(UTC)
    rows = (await session.execute(
        select(PreviewDeploy).where(PreviewDeploy.expires_at <= now, PreviewDeploy.closed_at.is_(None))
    )).scalars().all()
    for row in rows:
        # A missing container/route is already clean; a real removal failure
        # leaves the row open so the next sweep retries it. One bad row must
        # not wedge the rest of the sweep.
        cleanup_ok = True
        if row.container_id:
            try:
                await orchestrator.remove(row.container_id, force=True)
            except ContainerNotFoundError:
                pass
            except Exception:
                logger.exception("Preview GC could not remove container %s", row.container_id)
                cleanup_ok = False
        if row.container_name or row.route_host:
            try:
                await traffic_router.remove_route(row.container_name or row.route_host)
            except RouteNotFoundError:
                pass
            except Exception:
                logger.exception("Preview GC could not remove route for preview %s", row.id)
                cleanup_ok = False
        if not cleanup_ok:
            continue
        row.status = "expired"
        row.closed_at = now
    await session.commit()
    return len(rows)


async def teardown_preview(
    session: AsyncSession, row: PreviewDeploy, orchestrator, traffic_router,
    *, status: str = "closed",
) -> None:
    """Best-effort container/route removal for a closed or revoked preview."""
    if row.container_id:
        with suppress(Exception):
            await orchestrator.remove(row.container_id, force=True)
    if row.container_name or row.route_host:
        with suppress(Exception):
            await traffic_router.remove_route(row.container_name or row.route_host)
    row.status = status
    row.closed_at = datetime.now(UTC)
