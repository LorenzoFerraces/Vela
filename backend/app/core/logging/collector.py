"""Background log collector — tails Docker logs and batch-inserts into Postgres."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

import sqlalchemy as sa

from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.logging.inference import infer_log_level
from app.db.engine import get_session_factory
from app.db.models import ContainerLog, LogLevel, LogSource

logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("VELA_LOG_BATCH_SIZE", "100"))
COLLECT_INTERVAL = int(os.getenv("VELA_LOG_COLLECTOR_INTERVAL_SECONDS", "5"))
RETENTION_DAYS = int(os.getenv("VELA_LOG_RETENTION_DAYS", "7"))
MAX_LINES_PER_POLL = int(os.getenv("VELA_LOG_MAX_LINES_PER_POLL", "200"))
COLLECTOR_ENABLED = os.getenv("VELA_LOG_COLLECTOR_ENABLED", "1") != "0"

# ponytail: Docker log timestamps not exposed by SDK, use collection time with since= cursor
_DOCKER_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\s]*)\s+(stdout|stderr)\s+[IF]\s+")


async def batch_insert_logs(session, logs: list[ContainerLog]) -> None:
    if not logs:
        return
    session.add_all(logs)
    await session.commit()


async def cleanup_old_logs(session, retention_days: int = RETENTION_DAYS) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await session.execute(
        sa.delete(ContainerLog).where(ContainerLog.created_at < cutoff)
    )
    await session.commit()
    return result.rowcount


class LogCollector:
    def __init__(
        self,
        orchestrator: ContainerOrchestrator,
        *,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._session_factory = session_factory or get_session_factory
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_seen: dict[str, str] = {}

    async def start(self) -> None:
        if not COLLECTOR_ENABLED:
            logger.info("Log collector disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Log collector started (interval=%ds, retention=%dd)",
            COLLECT_INTERVAL,
            RETENTION_DAYS,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Log collector stopped")

    async def _run_loop(self) -> None:
        cycle = 0
        while self._running:
            try:
                cycle += 1
                await self._collect_cycle()
                if cycle % 10 == 0:
                    await self._cleanup()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Log collector cycle error")
            await asyncio.sleep(COLLECT_INTERVAL)

    async def _collect_cycle(self) -> None:
        containers = await self._orchestrator.list()
        all_logs: list[ContainerLog] = []
        now = datetime.now(timezone.utc)

        for container in containers:
            if container.status != "running":
                continue
            try:
                last_line = self._last_seen.get(container.id, "")
                raw = await self._orchestrator.logs(
                    container.id,
                    tail=MAX_LINES_PER_POLL,
                )
                lines = raw.strip().split("\n") if raw.strip() else []
                if not lines:
                    continue

                # ponytail: simple dedup — skip lines up to and including last seen
                skip = True
                for line in lines:
                    if skip and line == last_line:
                        continue
                    skip = False

                    parsed = _DOCKER_TS_RE.match(line)
                    if parsed:
                        try:
                            ts = datetime.fromisoformat(parsed.group(1).replace("Z", "+00:00"))
                        except ValueError:
                            ts = now
                        source = LogSource.STDERR if parsed.group(2) == "stderr" else LogSource.STDOUT
                        message = _DOCKER_TS_RE.sub("", line).strip()
                    else:
                        ts = now
                        source = LogSource.STDOUT
                        message = line

                    level = infer_log_level(message)
                    all_logs.append(
                        ContainerLog(
                            container_id=container.id,
                            container_name=container.name,
                            timestamp=ts,
                            source=source,
                            level=level,
                            message=message,
                        )
                    )

                if lines:
                    self._last_seen[container.id] = lines[-1]
            except Exception:
                logger.exception(
                    "Failed to collect logs for container %s", container.id
                )

        if not all_logs:
            return

        async with self._session_factory() as session:
            for batch_start in range(0, len(all_logs), BATCH_SIZE):
                batch = all_logs[batch_start : batch_start + BATCH_SIZE]
                await batch_insert_logs(session, batch)
            logger.debug("Inserted %d log entries", len(all_logs))

    async def _cleanup(self) -> None:
        try:
            async with self._session_factory() as session:
                deleted = await cleanup_old_logs(session)
                logger.info("Cleaned up %d old log entries", deleted)
        except Exception:
            logger.exception("Log cleanup error")


def create_log_collector() -> LogCollector:
    from app.api.deps import get_orchestrator

    return LogCollector(get_orchestrator())
