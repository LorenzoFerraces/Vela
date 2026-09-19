"""Unit tests for the in-memory deploy job registry (no app wiring)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.core.deploy.jobs import (
    TERMINAL_JOB_TTL,
    DeployJobRegistry,
    classify_deploy_error,
)
from app.core.exceptions import (
    ImageBuildError,
    NeedsBuildOverrideError,
    ProviderConnectionError,
)

PROJECT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _registry() -> DeployJobRegistry:
    return DeployJobRegistry()


def _job(registry: DeployJobRegistry, **overrides: object):
    params: dict[str, object] = {
        "kind": "container",
        "project_id": PROJECT_ID,
        "user_id": USER_ID,
        "name": "web",
        "source_label": "nginx:alpine",
    }
    params.update(overrides)
    return registry.create(**params)


def test_create_defaults_and_active_scope() -> None:
    registry = _registry()
    job = _job(registry)
    assert job.status == "in_progress"
    assert job.phase == "queued"
    assert job.services == []
    assert registry.active(project_ids={PROJECT_ID}) == [job]
    assert registry.active(project_ids={uuid.uuid4()}) == []


def test_stack_job_service_states_in_order() -> None:
    registry = _registry()
    job = _job(registry, kind="stack", services=["web", "api"])
    assert [(s.name, s.state) for s in job.services] == [
        ("web", "pending"),
        ("api", "pending"),
    ]
    registry.set_phase(job.job_id, "deploying")
    registry.set_service_state(job.job_id, "web", "building")
    registry.set_service_state(job.job_id, "web", "running")
    registry.set_service_state(job.job_id, "api", "failed")
    registry.complete_failure(
        job.job_id, {"code": "deploy_failed", "detail": "boom", "failed_service": "api"}
    )
    assert job.status == "failed"
    assert job.finished_at is not None
    assert [(s.name, s.state) for s in job.services] == [
        ("web", "running"),
        ("api", "failed"),
    ]
    assert registry.active(project_ids={PROJECT_ID}) == [job]


def test_terminal_jobs_swept_after_ttl() -> None:
    registry = _registry()
    job = _job(registry)
    registry.complete_failure(job.job_id, {"code": "deploy_failed", "detail": "boom"})
    job.finished_at = datetime.now(timezone.utc) - timedelta(
        seconds=TERMINAL_JOB_TTL + 1
    )
    assert registry.active(project_ids={PROJECT_ID}) == []
    assert registry.get(job.job_id) is None


def test_terminal_transition_is_idempotent() -> None:
    registry = _registry()
    job = _job(registry)
    registry.complete_failure(job.job_id, {"code": "deploy_failed", "detail": "first"})
    registry.complete_failure(job.job_id, {"code": "deploy_failed", "detail": "second"})
    registry.complete_success(job.job_id, {"ok": True})
    assert job.status == "failed"
    assert job.error is not None
    assert job.error["detail"] == "first"
    assert job.result is None


def test_classify_deploy_error_known_types() -> None:
    override = classify_deploy_error(NeedsBuildOverrideError("detection failed"))
    assert override == {"code": "needs_build_override", "detail": "detection failed"}

    build = classify_deploy_error(
        ImageBuildError("build blew up", build_log="step 1\nfailed")
    )
    assert build["code"] == "build_failed"
    assert build["detail"] == "build blew up"
    assert build["build_log"] == "step 1\nfailed"

    provider = classify_deploy_error(ProviderConnectionError("docker down"))
    assert provider == {"code": "provider_unavailable", "detail": "docker down"}

    other = classify_deploy_error(RuntimeError("weird"))
    assert other == {"code": "deploy_failed", "detail": "weird"}


def test_spawn_runs_coroutine_and_cancel_all_stops_workers() -> None:
    async def main() -> None:
        registry = _registry()
        job = _job(registry)
        started = asyncio.Event()

        async def worker() -> None:
            started.set()
            await asyncio.sleep(5)

        registry.spawn(job.job_id, worker())
        await asyncio.wait_for(started.wait(), timeout=1)
        await registry.cancel_all()

    asyncio.run(main())
