"""Background worker that polls Docker stats and persists to Postgres."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.containers.docker_orchestrator import VELA_MANAGED_LABEL
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import ProviderConnectionError
from app.db.models import ContainerMetric

logger = logging.getLogger(__name__)

METRICS_INTERVAL_SECONDS = int(
    os.environ.get("VELA_METRICS_INTERVAL_SECONDS", "30").strip()
)
METRICS_RETENTION_DAYS = int(
    os.environ.get("VELA_METRICS_RETENTION_DAYS", "30").strip()
)


async def collect_and_store_once(
    orchestrator: ContainerOrchestrator, session: AsyncSession,
) -> None:
    """Poll stats for all Vela-managed containers and persist one row each."""
    try:
        containers = await orchestrator.list()
    except ProviderConnectionError:
        logger.debug("Docker unavailable; skipping metrics collection pass")
        return

    vela_containers = [
        c for c in containers if VELA_MANAGED_LABEL in (c.labels or {})
    ]

    rows: list[ContainerMetric] = []
    for container in vela_containers:
        try:
            stats = await orchestrator.get_stats(container.id)
        except ProviderConnectionError:
            logger.debug(
                "Docker unavailable for %s; skipping", container.id
            )
            continue
        except Exception:
            logger.exception(
                "Failed to collect stats for container %s", container.id
            )
            continue

        rows.append(
            ContainerMetric(
                container_id=stats.container_id,
                timestamp=stats.timestamp,
                cpu_percent=stats.cpu_percent,
                memory_usage_bytes=stats.memory_usage_bytes,
                memory_limit_bytes=stats.memory_limit_bytes,
                memory_percent=stats.memory_percent,
                network_rx_bytes=stats.network_rx_bytes,
                network_tx_bytes=stats.network_tx_bytes,
            )
        )

    if rows:
        session.add_all(rows)
        await session.commit()
        logger.debug("Stored %d metric rows", len(rows))


async def cleanup_expired_metrics(session: AsyncSession) -> None:
    """Delete metric rows older than METRICS_RETENTION_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=METRICS_RETENTION_DAYS)
    result = await session.execute(
        delete(ContainerMetric).where(ContainerMetric.timestamp < cutoff)
    )
    await session.commit()
    if result.rowcount:
        logger.info("Cleaned up %d expired metric rows", result.rowcount)


async def run_metrics_collector(orchestrator: ContainerOrchestrator) -> None:
    """Continuous collection loop for the lifetime of the application."""
    from app.db.engine import get_session_factory

    logger.info(
        "Starting metrics collector (interval=%ds, retention=%dd)",
        METRICS_INTERVAL_SECONDS,
        METRICS_RETENTION_DAYS,
    )

    session_factory = get_session_factory()
    cleanup_counter = 0

    while True:
        try:
            async with session_factory() as session:
                await collect_and_store_once(orchestrator, session)

                # Run cleanup every 10 collection cycles (~5 min at 30s interval)
                cleanup_counter += 1
                if cleanup_counter >= 10:
                    cleanup_counter = 0
                    await cleanup_expired_metrics(session)
        except asyncio.CancelledError:
            logger.info("Metrics collector stopped")
            break
        except Exception:
            logger.exception("Unexpected error in metrics collector loop")

        await asyncio.sleep(METRICS_INTERVAL_SECONDS)
