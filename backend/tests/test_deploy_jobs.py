"""Tests for the in-memory deploy job registry and /api/deploys/active."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
from app.db.models import User

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


def _create_job(
    api_client: TestClient, seeded_user: User, **overrides: Any
):
    fastapi_app = cast(FastAPI, api_client.app)
    project_id = seeded_user.personal_project_id
    assert project_id is not None
    params: dict[str, Any] = {
        "kind": "container",
        "project_id": project_id,
        "user_id": seeded_user.id,
        "name": "web",
        "source_label": "nginx:alpine",
    }
    params.update(overrides)
    return fastapi_app.state.deploy_jobs.create(**params)


def test_active_deploys_requires_auth(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/api/deploys/active").status_code == 401


def test_active_deploys_lists_in_progress_job(
    api_client: TestClient, seeded_user: User
) -> None:
    job = _create_job(api_client, seeded_user)
    listed = api_client.get("/api/deploys/active")
    assert listed.status_code == 200
    jobs = listed.json()
    assert [entry["job_id"] for entry in jobs] == [job.job_id]
    assert jobs[0]["kind"] == "container"
    assert jobs[0]["status"] == "in_progress"
    assert jobs[0]["phase"] == "queued"
    assert jobs[0]["name"] == "web"
    assert jobs[0]["source_label"] == "nginx:alpine"
    assert jobs[0]["services"] == []
    assert jobs[0]["error"] is None
    assert jobs[0]["result"] is None
    assert jobs[0]["finished_at"] is None


def test_active_deploys_keeps_terminal_job_visible(
    api_client: TestClient, seeded_user: User
) -> None:
    job = _create_job(api_client, seeded_user)
    cast(FastAPI, api_client.app).state.deploy_jobs.complete_failure(
        job.job_id, {"code": "deploy_failed", "detail": "boom"}
    )
    jobs = api_client.get("/api/deploys/active").json()
    assert [entry["job_id"] for entry in jobs] == [job.job_id]
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["error"] == {"code": "deploy_failed", "detail": "boom"}


def test_active_deploys_scoped_to_caller_projects(
    api_client: TestClient,
    other_user_client: TestClient,
    seeded_user: User,
) -> None:
    job = _create_job(api_client, seeded_user)
    mine = {
        entry["job_id"] for entry in api_client.get("/api/deploys/active").json()
    }
    assert job.job_id in mine
    theirs = {
        entry["job_id"]
        for entry in other_user_client.get("/api/deploys/active").json()
    }
    assert job.job_id not in theirs


def test_active_deploys_unknown_project_404(api_client: TestClient) -> None:
    response = api_client.get(f"/api/deploys/active?project_id={uuid.uuid4()}")
    assert response.status_code == 404


def test_active_deploys_echoes_stack_services(
    api_client: TestClient, seeded_user: User
) -> None:
    job = _create_job(
        api_client, seeded_user, kind="stack", name="my-stack", services=["web", "api"]
    )
    jobs = api_client.get("/api/deploys/active").json()
    assert jobs[0]["kind"] == "stack"
    assert jobs[0]["services"] == [
        {"name": "web", "state": "pending"},
        {"name": "api", "state": "pending"},
    ]
    _ = job
