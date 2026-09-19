"""In-memory registry for async deploy jobs (202 + polled status).

Single-process app: the registry lives on ``app.state.deploy_jobs``, is created
in the app lifespan, and is mutated only from the event loop (workers are
coroutines; Docker SDK work already runs in the threadpool). Terminal jobs are
kept ``TERMINAL_JOB_TTL`` seconds (lazy sweep on access) so a 2.5s poller
always observes the terminal state. Jobs die with the process — same outcome
as the blocking deploy they replace.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine, Literal

from app.core.exceptions import (
    ImageBuildError,
    NeedsBuildOverrideError,
    ProviderConnectionError,
    VelaError,
)

DeployJobKind = Literal["container", "stack"]
DeployJobStatus = Literal["in_progress", "succeeded", "failed"]

TERMINAL_JOB_TTL = 300  # seconds a terminal job stays visible to pollers


class DeployError(VelaError):
    """Worker-side deploy failure carrying the structured error payload."""

    def __init__(self, error: dict[str, Any]) -> None:
        self.error = error
        super().__init__(
            str(error.get("detail", error.get("code", "deploy failed")))
        )


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
    return {"code": "deploy_failed", "detail": str(exc)}


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
        default_factory=lambda: datetime.now(timezone.utc)
    )
    finished_at: datetime | None = None


class DeployJobRegistry:
    """Deploy job store and detached-worker task holder (event-loop only)."""

    def __init__(self) -> None:
        self._jobs: dict[str, DeployJob] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def create(
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
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> DeployJob | None:
        return self._jobs.get(job_id)

    def set_phase(
        self, job_id: str, phase: str, phase_detail: str | None = None
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.phase = phase
        job.phase_detail = phase_detail

    def set_services(self, job_id: str, names: list[str]) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.services = [DeployServiceProgress(name=name) for name in names]

    def set_service_state(
        self, job_id: str, service_name: str, state: str
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        for service in job.services:
            if service.name == service_name:
                service.state = state
                return

    def complete_success(self, job_id: str, result: dict[str, Any]) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.status != "in_progress":
            return
        job.status = "succeeded"
        job.result = result
        job.finished_at = datetime.now(timezone.utc)

    def complete_failure(self, job_id: str, error: dict[str, Any]) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.status != "in_progress":
            return
        job.status = "failed"
        job.error = error
        job.finished_at = datetime.now(timezone.utc)

    def active(self, *, project_ids: set[uuid.UUID]) -> list[DeployJob]:
        """Visible jobs for the given projects, sweeping expired terminals."""
        self._sweep()
        return [
            job for job in self._jobs.values() if job.project_id in project_ids
        ]

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

    def _sweep(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=TERMINAL_JOB_TTL
        )
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.finished_at is not None and job.finished_at < cutoff
        ]
        for job_id in expired:
            del self._jobs[job_id]
