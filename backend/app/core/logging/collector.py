"""Background log collector — tails container logs and batch-inserts into Postgres."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from itertools import islice
from typing import Any

import sqlalchemy as sa

from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.logging.inference import infer_log_level
from app.db.engine import get_session_factory
from app.db.models import ContainerLog, LogSource

logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("VELA_LOG_BATCH_SIZE", "100"))
COLLECT_INTERVAL = int(os.getenv("VELA_LOG_COLLECTOR_INTERVAL_SECONDS", "5"))
RETENTION_DAYS = int(os.getenv("VELA_LOG_RETENTION_DAYS", "7"))
# ponytail: seed-poll backfill cap; cursor polls fetch only new lines (uncapped). Lines beyond
# 2000 per poll/interval are only lost on the first poll of a very chatty container — raise if real.
MAX_LINES_PER_POLL = int(os.getenv("VELA_LOG_MAX_LINES_PER_POLL", "2000"))
COLLECTOR_ENABLED = os.getenv("VELA_LOG_COLLECTOR_ENABLED", "1") != "0"
# ponytail: cap overlap scanning at 1024 lines per container per poll
_OVERLAP_CAP = 1024
# ponytail: bound parallel log fetches per poll so a large fleet can't hammer the provider API
_LOG_FETCH_CONCURRENCY = 8


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


def _fresh_lines(window: list[str], seen: deque[str]) -> list[str]:
    # ponytail: trim a re-emitted prefix whose content matches the tail of `seen` (line-granular,
    # capped at _OVERLAP_CAP). A window that is *entirely* a repeat is ambiguous — a heartbeat
    # continuation looks identical to a replay — and is kept whole; we lose nothing, a boundary
    # re-emit can at worst duplicate. Duplicates cost a row, loss costs the log.
    if not window or not seen:
        return window
    if window[0] not in seen:
        return window
    max_k = min(len(window), len(seen), _OVERLAP_CAP)
    for k in range(max_k, 0, -1):
        if list(islice(reversed(seen), k))[::-1] == window[:k]:
            if k == len(window):
                return window
            return window[k:]
    return window


class LogCollector:
    def __init__(
        self,
        orchestrator: ContainerOrchestrator,
        *,
        session_factory: Callable[[], Any] | None = None,
        enabled: bool = True,
        poll_interval: float | None = None,
        max_lines_per_poll: int | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._session_factory = session_factory or get_session_factory()
        self._enabled = enabled
        self._poll_interval = float(
            COLLECT_INTERVAL if poll_interval is None else poll_interval
        )
        self._max_lines = MAX_LINES_PER_POLL if max_lines_per_poll is None else max_lines_per_poll
        self._clock = clock or time.time
        self._running = False
        self._task: asyncio.Task[None] | None = None
        # ponytail: cursor = wall-clock unix seconds of the previous poll; log lines are stamped
        # in wall-clock time by every runtime, so the cursor stays valid across container restarts
        self._seen: dict[str, deque[str]] = {}
        self._cursor: dict[str, float] = {}
        self._fetch_semaphore = asyncio.Semaphore(_LOG_FETCH_CONCURRENCY)

    async def start(self) -> None:
        if not COLLECTOR_ENABLED or not self._enabled:
            logger.info("Log collector disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Log collector started (interval=%gs, retention=%dd)",
            self._poll_interval,
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
                await self.poll_once()
                if cycle % 10 == 0:
                    await self._cleanup()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Log collector cycle error")
            await asyncio.sleep(self._poll_interval)

    async def poll_once(self) -> None:
        if not self._enabled:
            return
        containers = await self._orchestrator.list()
        running = [c for c in containers if c.status == "running"]
        all_logs: list[ContainerLog] = []
        now = datetime.now(timezone.utc)

        async def _bounded_collect(container: Any) -> None:
            async with self._fetch_semaphore:
                try:
                    await self._collect_container(container, now, all_logs)
                except Exception:
                    logger.exception(
                        "Failed to collect logs for container %s", container.id
                    )

        await asyncio.gather(*(_bounded_collect(container) for container in running))

        if not all_logs:
            return

        async with self._session_factory() as session:
            for batch_start in range(0, len(all_logs), BATCH_SIZE):
                batch = all_logs[batch_start : batch_start + BATCH_SIZE]
                await batch_insert_logs(session, batch)
            logger.debug("Inserted %d log entries", len(all_logs))

    async def _collect_container(
        self, container: Any, now: datetime, out: list[ContainerLog]
    ) -> None:
        container_id = container.id
        cursor = self._cursor.get(container_id)
        if cursor is None:
            raw = await self._orchestrator.logs(container_id, tail=self._max_lines)
        else:
            raw = await self._orchestrator.logs(container_id, since=cursor)
        window = [line for line in raw.splitlines() if line]

        seen = self._seen.get(container_id)
        if seen is None:
            self._seen[container_id] = deque(window, maxlen=self._max_lines * 2)
            self._cursor[container_id] = self._clock()
            return

        for line in _fresh_lines(window, seen):
            out.append(
                ContainerLog(
                    container_id=container_id,
                    container_name=container.name,
                    timestamp=now,
                    source=LogSource.STDOUT,
                    level=infer_log_level(line),
                    message=line,
                )
            )
        seen.extend(window)
        self._cursor[container_id] = self._clock()

    async def _cleanup(self) -> None:
        try:
            async with self._session_factory() as session:
                deleted = await cleanup_old_logs(session)
                logger.info("Cleaned up %d old log entries", deleted)
        except Exception:
            logger.exception("Log cleanup error")
