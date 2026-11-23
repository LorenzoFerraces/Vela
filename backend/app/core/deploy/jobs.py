"""Postgres-backed registry for async deploy jobs (202 + polled status).

Jobs are persisted in the ``deploy_jobs`` table so they survive process
restarts. Terminal jobs are swept after ``TERMINAL_JOB_TTL`` (300 s) on each
``active()`` call, keeping the poller's terminal state visible. Detached worker
task handles stay on the event loop (workers are coroutines; Docker SDK work
already runs in the threadpool).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import (
    ImageBuildError,
    NeedsBuildOverrideError,
    ProviderConnectionError,
    VelaError,
)
from app.db.models import DeployJobRecord

DeployJobKind = Literal["container", "stack"]
DeployJobStatus = Literal["in_progress", "succeeded", "failed"]

TERMINAL_JOB_TTL = 300  # seconds a terminal job stays visible to pollers
ABANDONED_JOB_CUTOFF = timedelta(minutes=30)
ABANDONED_JOB_ERROR: dict[str, Any] = {
    "code": "deploy_failed",
    "detail": "abandoned by restart",
}


GENERIC_DEPLOY_FAILURE_DETAIL = "Deploy failed due to an unexpected error."


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; restore UTC for the public job payload."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def classify_deploy_error(exc: Exception) -> dict[str, Any]:
    """Map a worker exception to the client-facing job error contract."""
    if isinstance(exc, NeedsBuildOverrideError):
        content = exc.api_response_content()
        return {"code": content["code"], "detail": content["detail"]}
    if isinstance(exc, ImageBuildError):
        build_log = exc.build_log or ""
        return {
            "code": "build_failed",
            "detail": str(exc),
            "build_log": build_log[-65536:],
        }
    if isinstance(exc, ProviderConnectionError):
        return {"code": "provider_unavailable", "detail": str(exc)}
    if isinstance(exc, VelaError):
        return {"code": "deploy_failed", "detail": str(exc)}
    return {"code": "deploy_failed", "detail": GENERIC_DEPLOY_FAILURE_DETAIL}


@dataclass
class DeployServiceProgress:
    """Per-service progress for stack jobs (deploy/topo order)."""

    name: str
    state: str = "pending"  # pending | building | starting | running | failed


@dataclass
class DeployJob:
    kind: DeployJobKind
    project_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    source_label: str = ""
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: DeployJobStatus = "in_progress"
    phase: str = "queued"
    phase_detail: str | None = None
    services: list[DeployServiceProgress] = field(default_factory=list)
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    finished_at: datetime | None = None


class DeployJobRegistry:
    """Deploy job store and detached-worker task holder (event-loop only)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def create(
        self,
        *,
        kind: DeployJobKind,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        source_label: str = "",
        services: list[str] | None = None,
    ) -> DeployJob:
        job = DeployJob(
            kind=kind,
            project_id=project_id,
            user_id=user_id,
            name=name,
            source_label=source_label,
            services=[
                DeployServiceProgress(name=service_name)
                for service_name in (services or [])
            ],
        )
        async with self._session_factory() as session:
            session.add(self._to_record(job))
            await session.commit()
        return job

    async def get(self, job_id: str) -> DeployJob | None:
        async with self._session_factory() as session:
            record = await session.get(DeployJobRecord, job_id)
            return self._from_record(record) if record else None

    async def _update(
        self, job_id: str, change: Callable[[DeployJobRecord], None]
    ) -> None:
        async with self._session_factory() as session:
            record = await session.get(DeployJobRecord, job_id)
            if record is None:
                return
            change(record)
            await session.commit()

    async def set_phase(
        self, job_id: str, phase: str, phase_detail: str | None = None
    ) -> None:
        def change(record: DeployJobRecord) -> None:
            record.phase = phase
            record.phase_detail = phase_detail

        await self._update(job_id, change)

    async def set_services(self, job_id: str, names: list[str]) -> None:
        def change(record: DeployJobRecord) -> None:
            record.services = [{"name": name, "state": "pending"} for name in names]

        await self._update(job_id, change)

    async def set_service_state(
        self, job_id: str, service_name: str, state: str
    ) -> None:
        def change(record: DeployJobRecord) -> None:
            record.services = [
                {**item, "state": state} if item.get("name") == service_name else item
                for item in record.services
            ]

        await self._update(job_id, change)

    async def complete_success(self, job_id: str, result: dict[str, Any]) -> None:
        def change(record: DeployJobRecord) -> None:
            if record.status == "in_progress":
                record.status, record.result, record.finished_at = (
                    "succeeded",
                    result,
                    datetime.now(UTC),
                )

        await self._update(job_id, change)

    async def complete_failure(self, job_id: str, error: dict[str, Any]) -> None:
        def change(record: DeployJobRecord) -> None:
            if record.status == "in_progress":
                record.status, record.error, record.finished_at = (
                    "failed",
                    error,
                    datetime.now(UTC),
                )

        await self._update(job_id, change)

    async def active(self, *, project_ids: set[uuid.UUID]) -> list[DeployJob]:
        """Visible jobs for the given projects, sweeping expired terminals."""
        async with self._session_factory() as session:
            await session.execute(
                delete(DeployJobRecord).where(
                    DeployJobRecord.finished_at.is_not(None),
                    DeployJobRecord.finished_at
                    < datetime.now(UTC) - timedelta(seconds=TERMINAL_JOB_TTL),
                )
            )
            rows = (
                await session.execute(
                    select(DeployJobRecord).where(
                        DeployJobRecord.project_id.in_(project_ids)
                    )
                )
            ).scalars().all()
            await session.commit()
            return [self._from_record(row) for row in rows]

    def spawn(self, job_id: str, coro: Coroutine[Any, Any, None]) -> None:
        """Run the worker as a detached task; the registry holds the reference."""
        task = asyncio.create_task(coro)
        self._tasks[job_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(job_id, None))

    async def cancel_all(self) -> None:
        """Best-effort shutdown: cancel in-flight workers."""
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    @staticmethod
    def _to_record(job: DeployJob) -> DeployJobRecord:
        return DeployJobRecord(
            job_id=job.job_id,
            kind=job.kind,
            project_id=job.project_id,
            user_id=job.user_id,
            name=job.name,
            source_label=job.source_label,
            status=job.status,
            phase=job.phase,
            phase_detail=job.phase_detail,
            services=[
                {"name": service.name, "state": service.state}
                for service in job.services
            ],
            error=job.error,
            result=job.result,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )

    @staticmethod
    def _from_record(record: DeployJobRecord) -> DeployJob:
        return DeployJob(
            job_id=record.job_id,
            kind=cast(DeployJobKind, record.kind),
            project_id=record.project_id,
            user_id=record.user_id,
            name=record.name,
            source_label=record.source_label,
            status=cast(DeployJobStatus, record.status),
            phase=record.phase,
            phase_detail=record.phase_detail,
            services=[
                DeployServiceProgress(name=item["name"], state=item["state"])
                for item in record.services
            ],
            error=record.error,
            result=record.result,
            created_at=_as_utc(record.created_at),
            finished_at=(
                _as_utc(record.finished_at)
                if record.finished_at is not None
                else None
            ),
        )


async def fail_abandoned_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    cutoff: timedelta = ABANDONED_JOB_CUTOFF,
) -> int:
    """Mark in_progress jobs older than ``cutoff`` failed after a process restart.

    Called only on the replica that owns background loops, so a live worker on
    another replica is never reaped. Fresh jobs are left untouched.
    """
    threshold = datetime.now(UTC) - cutoff
    async with session_factory() as session:
        rows = (await session.execute(
            select(DeployJobRecord).where(
                DeployJobRecord.status == "in_progress",
                DeployJobRecord.created_at < threshold,
            )
        )).scalars().all()
        now = datetime.now(UTC)
        for record in rows:
            record.status = "failed"
            record.error = dict(ABANDONED_JOB_ERROR)
            record.finished_at = now
        await session.commit()
        return len(rows)
