"""Tests for the in-memory deploy job registry and /api/deploys/active."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
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
from app.db.models import DeploymentRecord, User

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


def _create_template(api_client: TestClient) -> str:
    response = api_client.post(
        "/api/dockerfiles/",
        json={"name": f"tpl-{uuid.uuid4().hex[:8]}", "contents": "FROM nginx:alpine\n"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _submit_run(api_client: TestClient, json_body: dict[str, Any]):
    return api_client.post("/api/containers/run", json=json_body)


def wait_for_deploy(
    client: TestClient, job_id: str, timeout: float = 10.0
) -> dict[str, Any]:
    """Poll /api/deploys/active until the job reaches a terminal state."""
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    # Outlast the detached worker so no poll's request-session teardown
    # ROLLBACK overlaps the worker's transaction on the shared in-memory
    # SQLite connection (the worker already finished when polling starts).
    time.sleep(0.2)
    while True:
        jobs = client.get("/api/deploys/active").json()
        last = next(
            (entry for entry in jobs if entry["job_id"] == job_id), None
        )
        if last is not None and last["status"] != "in_progress":
            return last
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"deploy job {job_id} did not finish in {timeout}s; last={last}"
            )
        time.sleep(0.1)


def test_run_returns_202_and_job_completes_with_run_response_shape(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    accepted = _submit_run(
        api_client,
        {
            "source_kind": "image",
            "image_ref": "nginx:alpine",
            "public_route": True,
            "container_port": 80,
            "env_vars": {"FOO": "bar"},
        },
    )
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["status"] == "in_progress"

    job = wait_for_deploy(api_client, body["job_id"])
    assert job["phase"] in {"starting", "routing"}
    assert job["status"] == "succeeded"
    result = job["result"]
    assert result["kind"] == "image"
    assert result["image"] == "nginx:alpine"
    assert result["route_wired"] is True
    assert result["public_url"].startswith("https://")
    assert result["container"]["status"] == "running"
    assert fake_orchestrator.last_deploy_config is not None


def test_run_job_persists_deployment_record(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_PUBLIC_ROUTE_DOMAIN", "apps.example.com")
    accepted = _submit_run(
        api_client,
        {"source_kind": "image", "image_ref": "nginx:alpine", "env_vars": {"FOO": "bar"}},
    )
    job = wait_for_deploy(api_client, accepted.json()["job_id"])
    assert job["status"] == "succeeded"

    listed = api_client.get("/api/deployments/")
    rows = listed.json()
    assert rows[0]["env_vars"] == {"FOO": "<REDACTED>"}


def test_run_job_error_contract_build_failure(
    api_client: TestClient,
    fake_orchestrator: FakeContainerOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_build(self, dockerfile_contents: str, *, tag: str):
        _ = self, dockerfile_contents, tag
        raise ImageBuildError("boom during build", build_log="step 1\nfailed")

    monkeypatch.setattr(
        "app.core.build.default_image_builder.DefaultImageBuilder.build_from_dockerfile_template",
        failing_build,
    )
    accepted = _submit_run(
        api_client,
        {
            "source_kind": "dockerfile_template",
            "dockerfile_template_id": _create_template(api_client),
        },
    )
    job = wait_for_deploy(api_client, accepted.json()["job_id"])
    assert job["status"] == "failed"
    assert job["error"]["code"] == "build_failed"
    assert job["error"]["detail"] == "boom during build"
    assert "failed" in job["error"]["build_log"]


def test_run_job_error_contract_needs_build_override(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def empty_clone(
        *, url: str, branch: str, dest: Path, access_token: str | None = None
    ) -> None:
        _ = url, branch, access_token
        dest.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "app.core.build.default_image_builder.git_shallow_clone", empty_clone
    )
    accepted = _submit_run(
        api_client,
        {"source": "https://github.com/example/empty.git", "git_branch": "main"},
    )
    job = wait_for_deploy(api_client, accepted.json()["job_id"])
    assert job["status"] == "failed"
    assert job["error"]["code"] == "needs_build_override"
    assert "detail" in job["error"]


def test_run_sync_400_stays_sync_for_missing_public_route_domain(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VELA_PUBLIC_ROUTE_DOMAIN", raising=False)
    response = _submit_run(
        api_client, {"source": "nginx:alpine", "public_route": True}
    )
    assert response.status_code == 400
    assert "VELA_PUBLIC_ROUTE_DOMAIN" in response.json()["detail"]


def test_run_sync_422_stays_sync_for_bad_payload(api_client: TestClient) -> None:
    assert (
        _submit_run(
            api_client,
            {
                "source_kind": "image",
                "image_ref": "nginx:alpine",
                "command": [],
            },
        ).status_code
        == 422
    )


def _create_stack(api_client: TestClient, name: str, services: list[dict[str, Any]]) -> str:
    created = api_client.post(
        "/api/stacks/", json={"name": name, "services": services}
    )
    assert created.status_code == 201
    return created.json()["id"]


def _image_service(name: str, ref: str, **extra: Any) -> dict[str, Any]:
    service = {
        "service_name": name,
        "source_kind": "image",
        "source_ref": ref,
        "container_port": 80,
        "env_vars": {},
        "public_route": False,
    }
    service.update(extra)
    return service


def test_stack_deploy_returns_202_and_completes(
    api_client: TestClient, fake_orchestrator: FakeContainerOrchestrator
) -> None:
    stack_id = _create_stack(
        api_client, "jobs-stack", [_image_service("web", "nginx:alpine")]
    )
    network_name = api_client.get(f"/api/stacks/{stack_id}").json()["network_name"]

    accepted = api_client.post(f"/api/stacks/{stack_id}/deploy")
    assert accepted.status_code == 202
    job = wait_for_deploy(api_client, accepted.json()["job_id"])
    assert job["kind"] == "stack"
    assert job["status"] == "succeeded"
    assert job["services"] == [{"name": "web", "state": "running"}]
    assert job["result"] == {
        "containers": [
            {
                "service_name": "web",
                "container_id": job["result"]["containers"][0]["container_id"],
                "container_name": job["result"]["containers"][0]["container_name"],
            }
        ]
    }
    assert network_name in fake_orchestrator._networks

    api_client.delete(f"/api/stacks/{stack_id}")


def test_stack_deploy_persist_survives_teardown_rollback(
    api_client: TestClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the shared-connection hazard deterministically: the first
    # commit that stages DeploymentRecords gets a competing ROLLBACK on
    # the shared in-memory connection between its flush and COMMIT — the
    # same interleaving a poll request's session teardown can cause.
    raced = False
    original_commit = AsyncSession.commit

    async def racy_commit(self: AsyncSession) -> None:
        nonlocal raced
        if not raced and any(
            isinstance(obj, DeploymentRecord) for obj in self.sync_session.new
        ):
            raced = True
            await self.flush()
            async with db_session_factory() as competitor:
                await competitor.execute(select(1))
                await competitor.rollback()
        await original_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", racy_commit)

    stack_id = _create_stack(
        api_client,
        "jobs-persist-stack",
        [
            _image_service("web", "nginx:alpine"),
            _image_service("api", "python:3.12-slim", depends_on=["web"]),
        ],
    )
    accepted = api_client.post(f"/api/stacks/{stack_id}/deploy")
    assert accepted.status_code == 202
    job = wait_for_deploy(api_client, accepted.json()["job_id"])
    assert job["status"] == "succeeded"

    listed = api_client.get("/api/deployments/")
    persisted_ids = {row["container_id"] for row in listed.json()}
    for container in job["result"]["containers"]:
        assert container["container_id"] in persisted_ids
    api_client.delete(f"/api/stacks/{stack_id}")


def test_stack_deploy_persist_commit_failure_never_fails_job(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The commit staging DeploymentRecords can fail mid-flush (e.g. an
    # IntegrityError from a concurrent writer on the shared test
    # connection). The persist retry must absorb it, retry, and never
    # fail the deploy job or leak raw SQLAlchemy text onto the job. The
    # failure is injected into the sync Session.flush that the real
    # Session.commit runs internally, after the flush has actually run, so
    # the commit machinery performs its internal rollback and detaches the
    # flushed records from the identity map — the state a real failed
    # commit leaves behind.
    from sqlalchemy.orm import Session

    raised = False
    original_flush = Session.flush

    def failing_flush(self: Session, *args: Any, **kwargs: Any) -> None:
        nonlocal raised
        if not raised and any(
            isinstance(obj, DeploymentRecord) for obj in self.new
        ):
            raised = True
            original_flush(self)
            raise IntegrityError(
                "INSERT INTO deployment_records (id) VALUES (?)",
                {"id": "persist-test"},
                Exception("UNIQUE constraint failed: deployment_records.id"),
            )
        original_flush(self, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", failing_flush)

    stack_id = _create_stack(
        api_client,
        "jobs-persist-fail-stack",
        [
            _image_service("web", "nginx:alpine"),
            _image_service("api", "python:3.12-slim", depends_on=["web"]),
        ],
    )
    accepted = api_client.post(f"/api/stacks/{stack_id}/deploy")
    assert accepted.status_code == 202
    job = wait_for_deploy(api_client, accepted.json()["job_id"])
    assert job["status"] == "succeeded"
    error_text = str(job.get("error") or "")
    assert "IntegrityError" not in error_text
    assert "sqlalchemy" not in error_text.lower()

    listed = api_client.get("/api/deployments/")
    persisted_ids = {row["container_id"] for row in listed.json()}
    for container in job["result"]["containers"]:
        assert container["container_id"] in persisted_ids
    api_client.delete(f"/api/stacks/{stack_id}")


def test_stack_deploy_partial_failure_reports_failed_service(
    api_client: TestClient, fake_orchestrator: FakeContainerOrchestrator
) -> None:
    fake_orchestrator.fail_deploy_for_image("python:3.12-slim")
    stack_id = _create_stack(
        api_client,
        "jobs-rollback-stack",
        [
            _image_service("web", "nginx:alpine"),
            _image_service("api", "python:3.12-slim", depends_on=["web"]),
        ],
    )
    network_name = api_client.get(f"/api/stacks/{stack_id}").json()["network_name"]

    accepted = api_client.post(f"/api/stacks/{stack_id}/deploy")
    assert accepted.status_code == 202
    job = wait_for_deploy(api_client, accepted.json()["job_id"])

    assert job["status"] == "failed"
    assert job["error"]["code"] == "deploy_failed"
    assert job["error"]["failed_service"] == "api"
    assert "api" in job["error"]["detail"]
    states = {service["name"]: service["state"] for service in job["services"]}
    assert states == {"web": "running", "api": "failed"}

    assert network_name not in fake_orchestrator._networks
    api_client.delete(f"/api/stacks/{stack_id}")


def test_stack_deploy_needs_build_override_job_error(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def empty_clone(
        *, url: str, branch: str, dest: Path, access_token: str | None = None
    ) -> None:
        _ = url, branch, access_token
        dest.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "app.core.build.default_image_builder.git_shallow_clone", empty_clone
    )
    stack_id = _create_stack(
        api_client,
        "jobs-override-stack",
        [
            {
                "service_name": "api",
                "source_kind": "git",
                "source_ref": "https://github.com/example/empty.git",
                "git_branch": "main",
                "container_port": 80,
                "env_vars": {},
                "public_route": False,
            }
        ],
    )
    accepted = api_client.post(f"/api/stacks/{stack_id}/deploy")
    assert accepted.status_code == 202
    job = wait_for_deploy(api_client, accepted.json()["job_id"])
    assert job["status"] == "failed"
    assert job["error"]["code"] == "needs_build_override"
    assert "api" in job["error"]["detail"]
    api_client.delete(f"/api/stacks/{stack_id}")


def test_stack_deploy_viewer_still_403_sync(
    api_client: TestClient, seeded_user: User
) -> None:
    # ownership check happens before the job exists (covered fully in
    # test_stack_permissions.py); here only the sync 404 path matters.
    assert api_client.post(f"/api/stacks/{uuid.uuid4()}/deploy").status_code == 404
