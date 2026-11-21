# Defect Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every finding in Waves A/B/C of the 2026-11-20 full-project review, as constrained by `docs/specs/2026-11-20-defect-remediation-design.md`, across backend, frontend, CLI, infra, CI and docs.

**Architecture:** The backend is a FastAPI app split into thin controllers (`app/api/routes/`), domain logic (`app/core/`) and SQLAlchemy models (`app/db/models.py`), tested with real wiring (TestClient + in-memory SQLite + `FakeContainerOrchestrator`). Shared-root fixes are preferred over per-caller guards. Frontend is React 19 + Vite with a brutalist token system; CLI is Bun/TypeScript. Each task is one sequential implementer subagent plus one reviewer.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic / pytest; React 19.2.4 / TypeScript 5.9.3 / Vite 8.0.1 / Playwright 1.51.0; Bun CLI 1.4.4 types; Docker Compose + Traefik v3.2 + nginx; GitHub Actions.

## Global Constraints

- Branch baseline: `fix/review-defect-remediation` branched from `dev` at `4b59b57`; design spec commit `17c90bb`. The commits `c03fcbd`, `f1517bb`, `aad7943` (and `35f0db9`, `834cceb`) live only on `fix/security-and-cli-hardening` and must be merged separately — do not revert or re-apply their unrelated parts. Tasks 7, 8, 13 and 14 note expected merge conflicts.
- No Wave D features (`docs/specs/2026-11-20-platform-features-design.md` is explicitly out of scope).
- Exact npm versions only (no `^`/`~`); `frontend/.npmrc` sets `save-exact=true`; npm, not pnpm. CLI Bun versions also exact.
- No raw hex/rgba in CSS or inline styles (only library props: xyflow, xterm, recharts).
- Backend verification (every task): `cd backend; $env:VELA_FAKE_ORCHESTRATOR="1"; $env:VELA_DATABASE_URL="sqlite+aiosqlite:///:memory:"; python -m pytest tests -q; ruff check .; mypy app/ tests/`.
- Frontend verification (every frontend task): `cd frontend; npm run build; npm run lint; npm run typecheck; npm run test:e2e`.
- Infra verification (Tasks 14): `docker compose -f docker-compose.yml config -q; docker compose up -d --build; docker compose ps` (confirm `migrate` completed, `api` healthy); `docker compose down`.
- CLI verification (Task 13): `cd cli; bun test; bunx tsc --noEmit; bun build --compile src/main.ts --outfile dist/vela`.
- Deslop every diff: remove unnecessary comments, abnormal `try`/`except` on trusted paths, `any` casts used only to silence types, and structure that diverges from surrounding code — without changing behavior except for clear bugs.
- Execute strictly sequentially: one implementer subagent per task, one reviewer after each, before the next task starts. Main session keeps only the ledger and short status reports.
- The three evidence reports named in the spec (`.subagent-reports/review-backend.md`, `review-frontend.md`, `review-cli-infra-product.md`) are **present in this worktree** and were used together with the approved spec and direct reads of the cited source files. Finding-level granularity is exact; no "best-effort" downgrades apply.

---

### Task 1: Router auth, admin gates, route-level auth test, audit events (F1–F3, F27)

**Files:**
- Create: `backend/tests/test_route_auth_regression.py`, `backend/tests/test_admin_gates.py`
- Modify: `backend/app/api/routes/traffic.py:13-50`, `backend/app/api/routes/images.py:33-67`, `backend/app/api/routes/builder.py:24-48`, `backend/app/api/routes/tokens.py:21-74`
- Test: `backend/tests/test_route_auth_regression.py`, `backend/tests/test_admin_gates.py`

**Interfaces:**
- Consumes: `get_current_user` / `require_admin` from `backend/app/api/deps.py:160,187`; `emit_audit_log(session, user_id, action, target_type, target_id, details=None)` from `backend/app/core/audit/service.py:45`.
- Produces: `APIRouter(dependencies=[Depends(get_current_user)])` on traffic/images/builder; audit actions `route.upsert`, `route.delete`, `image.pull`, `image.build`, `token.create`, `token.revoke`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_route_auth_regression.py`:
```python
"""Every non-public /api route must reject an anonymous request."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.api.routes import builder, images, traffic

PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/config",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/clerk/exchange",
    "/api/auth/github/start",
    "/api/auth/github/callback",
}


def test_every_non_public_api_route_requires_auth(anonymous_client: TestClient) -> None:
    for router in (traffic.router, images.router, builder.router):
        assert router.dependencies, f"{router.prefix or router} has no router-level auth"

    checked = 0
    for route in anonymous_client.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path in PUBLIC_PATHS:
            continue
        for method in getattr(route, "methods", set()) or set():
            if method in {"HEAD", "OPTIONS"}:
                continue
            resolved = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)
            response = anonymous_client.request(method, resolved)
            assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
            checked += 1
    assert checked > 20
```
Also add `backend/tests/test_admin_gates.py` (the `seeded_user` fixture is a student):
```python
from fastapi.testclient import TestClient

from app.core.auth.tokens import create_access_token
from app.core.traffic.traffic_models import BackendServer, RouteSpec
from app.db.models import User


def test_student_cannot_upsert_route(api_client: TestClient, seeded_user: User) -> None:
    api_client.headers["Authorization"] = f"Bearer {create_access_token(seeded_user.id)}"
    spec = RouteSpec(
        route_id="r1", host="app.example.test", path_prefix="/",
        backend_servers=[BackendServer(host="nginx", port=80)], tls_enabled=False,
    )
    response = api_client.post("/api/routes", json=spec.model_dump(mode="json"))
    assert response.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend; $env:VELA_FAKE_ORCHESTRATOR="1"; $env:VELA_DATABASE_URL="sqlite+aiosqlite:///:memory:"; python -m pytest tests/test_route_auth_regression.py tests/test_admin_gates.py -q`. Expected: first assertion fails (`traffic.router.dependencies` is empty) and student POST returns 200/422 instead of 403.

- [ ] **Step 3: Write minimal implementation** — router-level auth in three routers. `backend/app/api/routes/traffic.py`:
```python
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_traffic_router, require_admin
from app.core.audit.service import emit_audit_log
from app.db.models import User
```
Then replace the router declaration and the two mutating handlers:
```python
router = APIRouter(dependencies=[Depends(get_current_user)])
```
```python
@router.post("/routes", response_model=RouteInfo)
async def upsert_route(
    spec: RouteSpec,
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> RouteInfo:
    """Create or replace a route (admin only)."""
    result = await traffic_router.upsert_route(spec)
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="route.upsert",
        target_type="route",
        target_id=spec.route_id,
        details={"host": spec.host, "path_prefix": spec.path_prefix},
    )
    await session.commit()
    return result
```
```python
@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: str,
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> Response:
    """Remove a route (admin only)."""
    await traffic_router.remove_route(route_id)
    await emit_audit_log(
        session, user_id=current_user.id, action="route.delete",
        target_type="route", target_id=route_id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```
Add the imports actually used: `from sqlalchemy.ext.asyncio import AsyncSession`, `from app.api.deps import get_current_user, get_db, get_traffic_router, require_admin`, `from app.core.audit.service import emit_audit_log`, `from app.db.models import User`.

`backend/app/api/routes/images.py`:
```python
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_orchestrator, require_admin
from app.core.audit.service import emit_audit_log
from app.db.models import User

router = APIRouter(dependencies=[Depends(get_current_user)])
```
```python
@router.post("/pull")
async def pull_image(
    image: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
    tag: str = "latest",
) -> dict[str, str]:
    """Pull an image from a registry (admin only)."""
    await orchestrator.pull_image(image, tag=tag)
    ref = f"{image}:{tag}" if ":" not in image else image
    await emit_audit_log(
        session, user_id=current_user.id, action="image.pull",
        target_type="image", target_id=ref,
    )
    await session.commit()
    return {"detail": "ok", "ref": ref}


@router.post("/build")
async def build_image(
    body: ImageBuildRequest,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, str]:
    """Build from a server-local directory (admin only)."""
    ctx = validate_local_build_context(Path(body.context_path))
    ensure_dockerfile_for_build(ctx, dockerfile_name=body.dockerfile)
    image_id = await orchestrator.build_image(str(ctx), tag=body.tag, dockerfile=body.dockerfile)
    await emit_audit_log(
        session, user_id=current_user.id, action="image.build",
        target_type="image", target_id=body.tag, details={"image_id": image_id},
    )
    await session.commit()
    return {"image_id": image_id, "tag": body.tag}
```

`backend/app/api/routes/builder.py` — add `require_admin`, `get_db`, `AsyncSession`, `User`, `emit_audit_log`, change router to `APIRouter(dependencies=[Depends(get_current_user)])`, and gate the two host-level handlers:
```python
@router.post("/build", response_model=BuildResult)
async def build_from_source(
    body: BuilderBuildRequest,
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> BuildResult:
    """Full pipeline: clone or local path → ensure Dockerfile → docker build (admin only)."""
    result = await image_builder.build_from_source(
        body.source, tag=body.tag, override=body.build_override,
    )
    await emit_audit_log(
        session, user_id=current_user.id, action="builder.build",
        target_type="build", target_id=result.image_tag,
    )
    await session.commit()
    return result


@router.post("/analyze", response_model=ProjectInfo)
async def analyze(
    body: BuilderAnalyzeRequest,
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
    current_user: Annotated[User, Depends(require_admin)],
) -> ProjectInfo:
    """Inspect a local project directory (admin only)."""
    ctx = validate_local_build_context(Path(body.project_path))
    return await image_builder.analyze(str(ctx))
```
`analyze-source` keeps its existing caller-scoped signature (no admin gate).

`backend/app/api/routes/tokens.py` — add audit to create/revoke (no new gate):
```python
from app.core.audit.service import emit_audit_log
```
in `create_token`, after `record, minted = await create_api_token(...)`:
```python
    await emit_audit_log(
        session, user_id=user.id, action="token.create",
        target_type="token", target_id=str(record.id), details={"name": record.name},
    )
    await session.commit()
```
in `revoke_token`, before `await session.commit()`:
```python
    await emit_audit_log(
        session, user_id=user.id, action="token.revoke",
        target_type="token", target_id=str(token_id),
    )
```

- [ ] **Step 4: Run test to verify it passes** — same pytest command as Step 2. Expected: `2 passed` (one test in each of the two new files). Then `ruff check .` and `mypy app/ tests/`.

- [ ] **Step 5: Commit** — `git add backend/app/api/routes/{traffic,images,builder,tokens}.py backend/tests/test_route_auth_regression.py backend/tests/test_admin_gates.py && git commit -m "fix(api): require auth on all routes and admin gates on host mutations"`

---

### Task 2: Traefik backtick guard (F4)

**Files:**
- Modify: `backend/app/core/traffic/traefik_file_traffic_router.py:42-50`
- Test: `backend/tests/test_traefik_rules.py`

**Interfaces:**
- Consumes: `RouteConfigurationError` from `app/core/exceptions.py`; `_path_rule(path_prefix: str) -> str` from the modified module.
- Produces: `_path_rule` that rejects backticks and backslashes with `RouteConfigurationError`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_traefik_rules.py`:
```python
import pytest

from app.core.exceptions import RouteConfigurationError
from app.core.traffic.traefik_file_traffic_router import _path_rule


@pytest.mark.parametrize("prefix", ["/`", "/a`b", "/a\\b"])
def test_path_rule_rejects_traefik_expression_breakout(prefix: str) -> None:
    with pytest.raises(RouteConfigurationError):
        _path_rule(prefix)


def test_path_rule_accepts_normal_prefix() -> None:
    assert _path_rule("/apps/api") == "PathPrefix(`/apps/api`)"
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend; python -m pytest tests/test_traefik_rules.py -q`. Expected: 3 failures — backtick prefixes currently produce `PathPrefix(...)` instead of raising.

- [ ] **Step 3: Write minimal implementation** — replace `_path_rule` at `traefik_file_traffic_router.py:48-50` with:
```python
def _path_rule(path_prefix: str) -> str:
    if "`" in path_prefix or "\\" in path_prefix:
        raise RouteConfigurationError("path_prefix contains invalid characters")
    return f"PathPrefix(`{path_prefix}`)"
```

- [ ] **Step 4: Run test to verify it passes** — `cd backend; python -m pytest tests/test_traefik_rules.py -q`. Expected: `4 passed`. Then full backend gate (`pytest tests -q`, `ruff check .`, `mypy app/ tests/`).

- [ ] **Step 5: Commit** — `git add backend/app/core/traffic/traefik_file_traffic_router.py backend/tests/test_traefik_rules.py && git commit -m "fix(traffic): reject backticks in Traefik path prefixes"`

---

### Task 3: Stack delete auth ordering (F5)

**Files:**
- Modify: `backend/app/core/stacks/repository.py:152-170`, `backend/app/api/routes/stacks.py:231-270`
- Test: `backend/tests/test_stack_delete_auth.py`

**Interfaces:**
- Consumes: `require_membership(session, project_id, user_id)` and `can_write(role)` from `app/core/projects`; `Stack` from `app/db/models.py`; `FakeContainerOrchestrator` from conftest.
- Produces: `require_stack_write_access(session: AsyncSession, stack: Stack, user_id: uuid.UUID) -> None` in `core/stacks/repository.py`, called before the first Docker mutation in both delete paths.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_stack_delete_auth.py`:
```python
from fastapi.testclient import TestClient

from app.core.auth.tokens import create_access_token
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.models import ContainerInfo, ContainerStatus
from app.db.models import ProjectMembership, User


def test_viewer_delete_stack_is_403_and_docker_state_intact(
    api_client: TestClient,
    other_user_client: TestClient,
    seeded_user: User,
    seeded_other_user: User,
    fake_orchestrator: FakeContainerOrchestrator,
    db_session_factory,
) -> None:
    import asyncio

    async def make_viewer() -> None:
        async with db_session_factory() as session:
            session.add(ProjectMembership(
                project_id=seeded_user.personal_project_id,
                user_id=seeded_other_user.id,
                role="viewer",
            ))
            await session.commit()

    asyncio.run(make_viewer())

    created = api_client.post("/api/stacks/", json={
        "name": "guarded",
        "services": [{
            "service_name": "web", "source_kind": "image", "source_ref": "nginx:alpine",
            "container_port": 80, "public_route": False,
        }],
    })
    assert created.status_code == 201
    body = created.json()
    stack_id = body["id"]

    info = ContainerInfo.model_validate({
        "id": "stack-cid-1", "name": "guarded_web", "image": "nginx:alpine",
        "status": ContainerStatus.RUNNING,
        "created_at": "2026-04-01T12:00:00+00:00", "labels": {}, "ports": [],
    })
    fake_orchestrator.seed_container(info)
    network_name = body["network_name"]
    asyncio.run(fake_orchestrator.create_network(network_name))

    other_user_client.headers["Authorization"] = f"Bearer {create_access_token(seeded_other_user.id)}"
    response = other_user_client.delete(f"/api/stacks/{stack_id}")
    assert response.status_code == 403
    assert [c.name for c in fake_orchestrator.list()] == ["guarded_web"]
    assert network_name in fake_orchestrator._networks
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend; python -m pytest tests/test_stack_delete_auth.py -q`. Expected: 403 assertion fails (viewer gets 204) and/or container list is empty (docker mutation happened before the check).

- [ ] **Step 3: Write minimal implementation** — in `backend/app/core/stacks/repository.py` add helper and use it in `delete_stack()`:
```python
async def require_stack_write_access(
    session: AsyncSession,
    stack: Stack,
    user_id: uuid.UUID,
) -> None:
    """Raise ProjectAccessDeniedError unless ``user_id`` may write to ``stack``'s project."""
    from app.core.exceptions import ProjectAccessDeniedError
    from app.core.projects.enums import can_write

    membership = await require_membership(
        session, project_id=stack.project_id, user_id=user_id
    )
    if not can_write(membership.role):
        raise ProjectAccessDeniedError("You do not have permission to modify this stack.")
```
Replace the body of `delete_stack` (`:152-170`) with:
```python
async def delete_stack(
    session: AsyncSession,
    stack_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Delete a stack. User must have write access to the stack's project."""
    stack = await get_stack(session, stack_id, user_id)
    if stack is None:
        raise StackNotFoundError(str(stack_id))
    await require_stack_write_access(session, stack, user_id)
    await session.delete(stack)
```
In `backend/app/api/routes/stacks.py`, import `require_stack_write_access` from `app.core.stacks.repository` and insert the guard immediately after the 404 check in `delete_user_stack` **before** `orchestrator.list()`:
```python
    stack = await get_stack(session, stack_id, current_user.id)
    if stack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Stack not found.")
    await require_stack_write_access(session, stack, current_user.id)
    containers = await orchestrator.list()
```
(Leave the later `await delete_stack(...)` call — the double check is harmless and keeps the repository self-contained. The existing `_require_stack_write_access` helper in `stacks.py` stays for create/deploy.)

- [ ] **Step 4: Run test to verify it passes** — `cd backend; python -m pytest tests/test_stack_delete_auth.py -q`. Expected: `1 passed`. Then full backend gate.

- [ ] **Step 5: Commit** — `git add backend/app/core/stacks/repository.py backend/app/api/routes/stacks.py backend/tests/test_stack_delete_auth.py && git commit -m "fix(stacks): check write access before any Docker mutation on delete"`

---

### Task 4: Replica runtime config from stored deploy configuration (F6)

**Files:**
- Create: `backend/alembic/versions/0023_deploy_config_snapshot.py`
- Modify: `backend/app/db/models.py:330-341`, `backend/app/core/deploy/deployment_history.py:18-60`, `backend/app/api/routes/containers.py:374-412`, `backend/app/core/scaling/scaling_engine.py:128-172,226-250`
- Test: `backend/tests/test_replica_config.py`

**Interfaces:**
- Consumes: `DeployConfig` (`app/core/models.py`), `record_deployment` / `DeploymentSnapshot` (Task 4 modified), `orchestrator.deploy_replica(config, index)`.
- Produces: `DeploymentRecord.deploy_config: dict | None`, `load_deploy_config_snapshot(session, container_id: str) -> DeployConfig | None` in `core/deploy/deployment_history.py` (keyed by the **Docker container id** written at `containers.py:395`, never by container name), `async def _base_container_info(orchestrator, base_name: str) -> ContainerInfo | None` in `core/scaling/scaling_engine.py` for name→id resolution, and `_scale_up(..., base_config: DeployConfig)` signature used by `_evaluate_policy`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_replica_config.py`:
```python
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.models import ContainerInfo, ContainerStatus, DeployConfig
from app.core.scaling.scaling_engine import _base_container_info, build_replica_config


def test_replica_config_preserves_env_command_limits_and_network() -> None:
    config = DeployConfig(
        image="nginx:alpine", name="api", container_port=8080,
        env_vars={"MODE": "prod"}, command=["nginx", "-g", "daemon off;"],
        cpu_limit=0.5, memory_limit=256, labels={"vela.project_id": "p1"},
    )
    replica = build_replica_config(config, 2)
    assert replica.image == "nginx:alpine"
    assert replica.env_vars == {"MODE": "prod"}
    assert replica.command == ["nginx", "-g", "daemon off;"]
    assert replica.cpu_limit == 0.5
    assert replica.memory_limit == 256
    assert replica.labels == config.labels
    assert replica.name == "api-r2"
```
Add an integration test that the snapshot round-trips:
```python
import uuid

from app.core.deploy.deployment_history import DeploymentSnapshot, load_deploy_config_snapshot, record_deployment
from app.core.models import DeployConfig


def test_deploy_config_snapshot_round_trip(db_session_factory, seeded_user) -> None:
    import asyncio

    config = DeployConfig(image="nginx:alpine", name="api", container_port=80, env_vars={"A": "B"})

    async def run() -> None:
        async with db_session_factory() as session:
            await record_deployment(
                session, user_id=seeded_user.id,
                project_id=seeded_user.personal_project_id,
                snapshot=DeploymentSnapshot(
                    container_id="cid-snap", container_name="api",
                    source_kind="image", source_ref="nginx:alpine", git_branch=None,
                    image_tag="nginx:alpine", container_port=80,
                    env_vars={}, command=None, dockerfile_snapshot=None, public_url=None,
                    deploy_config=config.model_dump(mode="json"),
                ),
            )
        async with db_session_factory() as session:
            loaded = await load_deploy_config_snapshot(session, "cid-snap")
            assert loaded is not None
            assert loaded.env_vars["A"] == "B"
            # The lookup is keyed by Docker id; the policy's name must not match.
            assert await load_deploy_config_snapshot(session, "api") is None

    asyncio.run(run())


def test_base_container_info_resolves_policy_name_to_docker_id(
    fake_orchestrator: FakeContainerOrchestrator,
) -> None:
    import asyncio

    info = ContainerInfo.model_validate({
        "id": "cid-real", "name": "api", "image": "nginx:alpine",
        "status": ContainerStatus.RUNNING,
        "created_at": "2026-04-01T12:00:00+00:00", "labels": {}, "ports": [],
    })
    fake_orchestrator.seed_container(info)
    resolved = asyncio.run(_base_container_info(fake_orchestrator, "api"))
    assert resolved is not None
    assert resolved.id == "cid-real"
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend; python -m pytest tests/test_replica_config.py -q`. Expected: `ImportError: cannot import name 'build_replica_config'` / `'_base_container_info'` and `TypeError: unexpected keyword 'deploy_config'`.

- [ ] **Step 3: Write minimal implementation** — add the column in `backend/app/db/models.py` after `build_override` (`DeploymentRecord`, line 340):
```python
    deploy_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```
Create `backend/alembic/versions/0023_deploy_config_snapshot.py`:
```python
"""Persist the full deploy config used to create a container.

Revision ID: 0023_deploy_config_snapshot
Revises: 0022_api_tokens
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0023_deploy_config_snapshot"
down_revision: str | None = "0022_api_tokens"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("deployment_records", sa.Column("deploy_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployment_records", "deploy_config")
```
In `backend/app/core/deploy/deployment_history.py`, add `deploy_config: dict | None = None` to `DeploymentSnapshot`, pass `deploy_config=snapshot.deploy_config` in `record_deployment`, and add:
```python
async def load_deploy_config_snapshot(
    session: AsyncSession, container_id: str
) -> DeployConfig | None:
    """Return the full DeployConfig recorded for ``container_id``, or None."""
    result = await session.execute(
        select(DeploymentRecord.deploy_config)
        .where(DeploymentRecord.container_id == container_id)
        .order_by(DeploymentRecord.created_at.desc())
    )
    raw = result.scalar_one_or_none()
    if raw is None:
        return None
    return DeployConfig.model_validate(raw)
```
with `from app.core.models import DeployConfig` at the top.

In `backend/app/api/routes/containers.py`, add `deploy_config=config.model_dump(mode="json")` to the `DeploymentSnapshot(...)` construction inside `_persist_run_deployment` (the `config` argument is not currently passed — add a `deploy_config: dict` keyword parameter to `_persist_run_deployment` and pass `config.model_dump(mode="json")` from each of its three call sites in `_run_container_deploy_worker`: the `image`, `dockerfile_template` and `git` branches).

In `backend/app/core/scaling/scaling_engine.py`, add:
```python
def build_replica_config(base: DeployConfig, index: int) -> DeployConfig:
    """Derive a replica config from the stored deploy config (not lossy inspection data)."""
    return base.model_copy(update={
        "name": f"{base.name}-r{index}",
        "ports": [],
        "route_host": None,
        "public_route": False,
    })
```
Add the name→Docker-id resolver next to `build_replica_config`:
```python
async def _base_container_info(
    orchestrator: ContainerOrchestrator, base_name: str
) -> ContainerInfo | None:
    """Resolve a policy's container name to the live container and its Docker id."""
    return next(
        (info for info in await orchestrator.list() if info.name == base_name),
        None,
    )
```
Change `_scale_up` signature to accept `base_config: DeployConfig` instead of constructing one from `base_info`; delete the `orchestrator.get(base_name)` call and the `DeployConfig(...)` block at lines 139-152. Replace the body's deploy call with `replica_info = await orchestrator.deploy_replica(build_replica_config(base_config, next_index), next_index)`. In `_evaluate_policy`, resolve the Docker id **first**, then load the snapshot by that id before the scale decision:
```python
    from app.core.deploy.deployment_history import load_deploy_config_snapshot

    base_info = await _base_container_info(orchestrator, base_name)
    if base_info is None:
        logger.warning("Scale-up skipped: base container %s not found", base_name)
        return
    base_config = await load_deploy_config_snapshot(session, base_info.id)
```
`base_name` is `policy.container_name` (`scaling_engine.py:233`); it is a container name, while snapshots store `container_id=info.id` (`containers.py:395`). Passing `base_name` directly would always miss and silently disable scaling. Pass `base_config` to `_scale_up`. If `base_config is None`, log a warning and `return` — never silently default runtime fields away.

- [ ] **Step 4: Run test to verify it passes** — `cd backend; python -m pytest tests/test_replica_config.py -q`. Expected: `3 passed`. Then full backend gate and `cd backend; alembic upgrade head` against a scratch DB to confirm the migration applies.

- [ ] **Step 5: Commit** — `git add backend/alembic/versions/0023_deploy_config_snapshot.py backend/app/db/models.py backend/app/core/deploy/deployment_history.py backend/app/api/routes/containers.py backend/app/core/scaling/scaling_engine.py backend/tests/test_replica_config.py && git commit -m "fix(scaling): build replicas from persisted deploy config"`

---

### Task 5: Upload reads, quotas and containment (F7, F22, F23)

**Files:**
- Modify: `backend/app/core/containers/volume_uploads.py:17-18,121-176`, `backend/app/api/routes/containers.py:792-865`, `backend/app/api/routes/users.py:49-72`
- Test: `backend/tests/test_upload_limits.py`

**Interfaces:**
- Consumes: `UploadFile` (Starlette), `MAX_AVATAR_BYTES` from `app/core/profile/service.py:19`, `VolumeUploadTooLargeError` / `VolumeUploadQuotaExceededError` from `app/core/exceptions.py`.
- Produces: `async def read_upload_limited(upload: UploadFile, limit: int) -> bytes`, `def upload_lock_for_user(user_id: uuid.UUID) -> asyncio.Lock`, and `Path.is_relative_to` based containment in `resolve_volume_upload_path`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_upload_limits.py`:
```python
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.containers import volume_uploads
from app.core.exceptions import InvalidVolumeUploadPathError


class _FakeUpload:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


@pytest.mark.asyncio
async def test_read_upload_limited_enforces_limit_while_streaming() -> None:
    upload = _FakeUpload([b"a" * 64, b"b" * 64])
    with pytest.raises(Exception) as exc:
        await volume_uploads.read_upload_limited(upload, 100)  # type: ignore[arg-type]
    assert type(exc.value).__name__ == "VolumeUploadTooLargeError"


def test_clamped_declared_size_is_ignored() -> None:
    """A client may claim size=1 while sending more bytes; the stream enforces the limit."""
    upload = _FakeUpload([b"x" * 200])
    import asyncio
    with pytest.raises(Exception) as exc:
        asyncio.run(volume_uploads.read_upload_limited(upload, 100))  # type: ignore[arg-type]
    assert type(exc.value).__name__ == "VolumeUploadTooLargeError"


def test_resolve_upload_path_rejects_sibling_prefix(monkeypatch, tmp_path) -> None:
    user_id = uuid.uuid4()
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path))
    victim = tmp_path / f"{user_id}-evil" / "x"
    victim.mkdir(parents=True)
    with pytest.raises(InvalidVolumeUploadPathError):
        volume_uploads.resolve_volume_upload_path(user_id, uuid.uuid4())
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend; python -m pytest tests/test_upload_limits.py -q`. Expected: `AttributeError: module ... has no attribute 'read_upload_limited'` for the first two tests; the containment test passes only after Step 3.

- [ ] **Step 3: Write minimal implementation** — in `backend/app/core/containers/volume_uploads.py` add imports `import asyncio` and `from fastapi import UploadFile`, then:
```python
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_upload_locks: dict[uuid.UUID, asyncio.Lock] = {}


def upload_lock_for_user(user_id: uuid.UUID) -> asyncio.Lock:
    """Per-user lock so concurrent uploads cannot race past the quota check.

    # ponytail: process-local only; multiple API workers need a shared quota counter.
    """
    lock = _upload_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _upload_locks[user_id] = lock
    return lock


async def read_upload_limited(upload: UploadFile, limit: int) -> bytes:
    """Read an upload in chunks, rejecting it before the full body is buffered."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            limit_megabytes = limit // (1024 * 1024)
            raise VolumeUploadTooLargeError(
                f"Folder exceeds the {limit_megabytes} MB upload limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)
```
Replace `resolve_volume_upload_path` containment check (`:164-169`):
```python
def resolve_volume_upload_path(user_id: uuid.UUID, upload_id: uuid.UUID) -> Path:
    root = upload_directory(user_id, upload_id).resolve()
    user_root = user_uploads_root(user_id).resolve()
    if not root.is_relative_to(user_root):
        msg = "Volume upload not found."
        raise VolumeUploadNotFoundError(msg)
    if not root.is_dir():
        msg = "Volume upload not found."
        raise VolumeUploadNotFoundError(msg)
    host_root = volume_uploads_host_root()
    if host_root is not None:
        return host_root / root.relative_to(volume_uploads_root())
    return root
```
In `backend/app/api/routes/containers.py`, import `read_upload_limited` / `upload_lock_for_user`, and rewrite the body of `upload_volume_folder` so the whole read/check/save runs under the user lock and never trusts `upload.size`:
```python
    if not files:
        raise InvalidVolumeUploadPathError(
            "Select a folder that contains at least one file."
        )

    per_folder_limit = volume_upload_max_bytes()
    user_quota = volume_upload_user_quota_bytes()
    async with upload_lock_for_user(current_user.id):
        current_usage = user_uploads_total_bytes(current_user.id)
        payloads: list[tuple[str, bytes]] = []
        total_bytes = 0
        for upload in files:
            relative_path = upload.filename or ""
            content = await read_upload_limited(upload, per_folder_limit - total_bytes)
            total_bytes += len(content)
            if current_usage + total_bytes > user_quota:
                limit_megabytes = user_quota // (1024 * 1024)
                raise VolumeUploadQuotaExceededError(
                    f"Upload would exceed your {limit_megabytes} MB volume storage quota. "
                    "Use a smaller folder or remove unused uploads."
                )
            payloads.append((relative_path, content))

        personal_project_id = await get_personal_project_id(session, current_user)
        personal_project = await session.get(Project, personal_project_id)
        team_quota = (
            effective_quota_bytes(personal_project) if personal_project is not None else None
        )
        if team_quota is not None:
            disk_bytes, uploads_bytes = await team_storage_usage(
                session, orchestrator, personal_project_id
            )
            used_bytes = disk_bytes + uploads_bytes
            if used_bytes + total_bytes > team_quota:
                raise TeamStorageQuotaExceededError(
                    f"Upload would exceed the team's {format_gib(team_quota)} "
                    f"storage quota ({format_gib(used_bytes)} used). "
                    "Use a smaller folder or remove unused uploads."
                )

        upload_id, folder_name, saved_bytes, file_count = save_volume_upload(
            current_user.id, payloads,
        )
    return VolumeUploadResponse(
        upload_id=upload_id, folder_name=folder_name, total_bytes=saved_bytes,
        file_count=file_count, max_bytes=per_folder_limit,
        user_quota_bytes=user_quota,
        user_used_bytes=user_uploads_total_bytes(current_user.id),
    )
```
In `backend/app/api/routes/users.py`, import `MAX_AVATAR_BYTES` and `read_upload_limited`, then replace line 57:
```python
    body = await read_upload_limited(file, MAX_AVATAR_BYTES + 1)
```
(`upload_avatar` keeps its own strict `> MAX_AVATAR_BYTES` check and produces `AvatarValidationError`; the `+1` lets it produce the client-facing message instead of a generic size error.)

- [ ] **Step 4: Run test to verify it passes** — `cd backend; python -m pytest tests/test_upload_limits.py -q`. Expected: `3 passed`. Then full backend gate.

- [ ] **Step 5: Commit** — `git add backend/app/core/containers/volume_uploads.py backend/app/api/routes/containers.py backend/app/api/routes/users.py backend/tests/test_upload_limits.py && git commit -m "fix(uploads): stream size limits, atomic quota checks, path containment"`

---

### Task 6: PAT expiry / last-used / scope + migration (F11)

**Files:**
- Create: `backend/alembic/versions/0024_api_token_lifecycle.py`
- Modify: `backend/app/db/models.py:657-682`, `backend/app/core/auth/api_tokens.py:39-63`, `backend/app/api/schemas.py:737-749`, `backend/app/api/routes/tokens.py:21-55`
- Test: `backend/tests/test_token_lifecycle.py`

**Interfaces:**
- Consumes: `ApiToken` model, `create_api_token` (Task 1 added audit in `tokens.py`), `get_user_by_api_token` used by `get_current_user` (`deps.py:167`).
- Produces: `create_api_token(session, user_id, name, *, expires_at=None, scope="full")`, `ApiToken.expires_at`, `ApiToken.last_used_at`, `ApiToken.scope`, and `load` behaviour that filters expired tokens and stamps `last_used_at`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_token_lifecycle.py`:
```python
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.auth.api_tokens import create_api_token, get_user_by_api_token
from app.db.models import ApiToken


@pytest.mark.asyncio
async def test_expired_token_is_rejected(db_session_factory, seeded_user) -> None:
    async with db_session_factory() as session:
        record, minted = await create_api_token(
            session, seeded_user.id, "old",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert await get_user_by_api_token(session, minted.plaintext) is None


@pytest.mark.asyncio
async def test_valid_token_records_last_used(db_session_factory, seeded_user) -> None:
    async with db_session_factory() as session:
        record, minted = await create_api_token(session, seeded_user.id, "live")
        user = await get_user_by_api_token(session, minted.plaintext)
        assert user is not None
    async with db_session_factory() as session:
        stored = await session.get(ApiToken, record.id)
        assert stored is not None and stored.last_used_at is not None


def test_create_token_api_accepts_scope_and_expiry(api_client, seeded_user) -> None:
    response = api_client.post("/api/tokens/", json={
        "name": "cli", "scope": "read", "expires_in_days": 30,
    })
    assert response.status_code == 201
    body = response.json()
    assert body["scope"] == "read"
    assert body["expires_at"] is not None
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend; python -m pytest tests/test_token_lifecycle.py -q`. Expected: `TypeError` on `expires_at`/`scope` kwargs and 422 on the POST.

- [ ] **Step 3: Write minimal implementation** — add to `ApiToken` in `backend/app/db/models.py` (after `token_hash`, line 677):
```python
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="full", server_default="full"
    )
```
Create `backend/alembic/versions/0024_api_token_lifecycle.py`:
```python
"""Add expiry, last-used and scope to API tokens.

Revision ID: 0024_api_token_lifecycle
Revises: 0023_deploy_config_snapshot
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0024_api_token_lifecycle"
down_revision: str | None = "0023_deploy_config_snapshot"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("api_tokens", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_tokens", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "api_tokens",
        sa.Column("scope", sa.String(32), nullable=False, server_default="full"),
    )


def downgrade() -> None:
    op.drop_column("api_tokens", "scope")
    op.drop_column("api_tokens", "last_used_at")
    op.drop_column("api_tokens", "expires_at")
```
Existing rows get `scope='full'` and NULL `expires_at` → non-expiring, so CLI tokens keep working.

Rewrite `backend/app/core/auth/api_tokens.py`:
```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
```
```python
async def create_api_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    *,
    expires_at: datetime | None = None,
    scope: str = "full",
) -> tuple[ApiToken, MintedApiToken]:
    minted = mint_api_token()
    record = ApiToken(
        user_id=user_id,
        name=name,
        token_prefix=minted.prefix,
        token_hash=minted.token_hash,
        expires_at=expires_at,
        scope=scope,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record, minted


async def get_user_by_api_token(
    session: AsyncSession, plaintext: str
) -> User | None:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(User, ApiToken.id)
        .join(ApiToken, ApiToken.user_id == User.id)
        .where(
            ApiToken.token_hash == hash_api_token(plaintext),
            (ApiToken.expires_at.is_(None)) | (ApiToken.expires_at > now),
        )
    )
    row = result.one_or_none()
    if row is None:
        return None
    user, token_id = row
    await session.execute(
        update(ApiToken).where(ApiToken.id == token_id).values(last_used_at=now)
    )
    await session.commit()
    return user
```
In `backend/app/api/schemas.py`, replace `ApiTokenCreate` / `ApiTokenPublic`:
```python
class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scope: Literal["full", "read"] = "full"
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiTokenPublic(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scope: str
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
```
Ensure `from typing import Literal` exists in `schemas.py`. In `backend/app/api/routes/tokens.py`:
```python
from datetime import datetime, timedelta, timezone
```
```python
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None
        else None
    )
    record, minted = await create_api_token(
        session, user.id, body.name, expires_at=expires_at, scope=body.scope
    )
    return ApiTokenCreated(
        id=record.id, name=record.name, prefix=record.token_prefix,
        scope=record.scope, created_at=record.created_at,
        expires_at=record.expires_at, last_used_at=record.last_used_at,
        token=minted.plaintext,
    )
```
and in `list_tokens` include `scope=record.scope, expires_at=record.expires_at, last_used_at=record.last_used_at`.

- [ ] **Step 4: Run test to verify it passes** — `cd backend; python -m pytest tests/test_token_lifecycle.py -q`. Expected: `3 passed`. Then full backend gate plus `alembic upgrade head` on a scratch DB.

- [ ] **Step 5: Commit** — `git add backend/alembic/versions/0024_api_token_lifecycle.py backend/app/db/models.py backend/app/core/auth/api_tokens.py backend/app/api/schemas.py backend/app/api/routes/tokens.py backend/tests/test_token_lifecycle.py && git commit -m "fix(auth): add PAT expiry, scope and last-used tracking"`

---

### Task 7: Auth hardening — throttle, Clerk, JWT, WebSocket auth/ticket (F8, F12, F13, F15, M7)

**Files:**
- Create: `backend/app/core/auth/rate_limit.py`, `backend/app/core/auth/ws_tickets.py`, `backend/tests/test_auth_hardening.py`
- Modify: `backend/app/api/routes/auth.py:66-117`, `backend/app/api/routes/tokens.py:21-34`, `backend/app/core/oauth/clerk.py:105-124,176-254`, `backend/app/core/auth/tokens.py:15-91`, `backend/app/api/routes/containers.py:161-175,1361-1408,1410-1429`, `backend/tests/conftest.py`, `frontend/playwright.config.ts:49-63`
- Test: `backend/tests/test_auth_hardening.py`

**Interfaces:**
- Consumes: `NotAuthenticatedError`, `IntegrationConfigurationError`, `PermissionDeniedError`, `emit_audit_log`, `require_container_access`, `_get_websocket_user`.
- Produces: `check_rate_limit(key: str) -> None` and `client_identity(request: Request) -> str` (`core/auth/rate_limit.py`); `issue_ws_ticket(user_id: uuid.UUID, container_id: str, purpose: str) -> str`, `consume_ws_ticket(ticket: str, container_id: str, purpose: str) -> uuid.UUID | None` (`core/auth/ws_tickets.py`); `POST /api/containers/{container_id}/ws-ticket?purpose=logs|exec` returning `{"ticket": str}`; JWT now carries `iss`/`aud`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_auth_hardening.py`:
```python
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.auth import rate_limit
from app.core.auth.tokens import create_access_token, decode_access_token
from app.core.auth.ws_tickets import consume_ws_ticket, issue_ws_ticket
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.models import ContainerInfo, ContainerStatus
from app.db.models import User


def test_rate_limit_blocks_eleventh_attempt() -> None:
    rate_limit.reset_for_tests()
    for _ in range(10):
        rate_limit.check_rate_limit("1.2.3.4")
    with pytest.raises(Exception) as exc:
        rate_limit.check_rate_limit("1.2.3.4")
    assert getattr(exc.value, "status_code", None) == 429


def test_jwt_carries_and_verifies_issuer_audience() -> None:
    claims = decode_access_token(create_access_token(uuid.uuid4()))
    assert claims.issuer == "vela"
    assert claims.audience == "vela-api"


def test_ws_ticket_is_single_use_and_scoped() -> None:
    user_id, container_id = uuid.uuid4(), "cid-1"
    ticket = issue_ws_ticket(user_id, container_id, "logs")
    assert consume_ws_ticket(ticket, container_id, "logs") == user_id
    assert consume_ws_ticket(ticket, container_id, "logs") is None
    other = issue_ws_ticket(user_id, container_id, "logs")
    assert consume_ws_ticket(other, "cid-2", "logs") is None
    assert consume_ws_ticket(other, container_id, "exec") is None


def test_ws_ticket_endpoint_requires_auth(
    api_client: TestClient,
    anonymous_client: TestClient,
    seeded_user: User,
    fake_orchestrator: FakeContainerOrchestrator,
) -> None:
    """Seed via the existing fake-orchestrator fixture; assert both anonymous rejection and auth success."""
    fake_orchestrator.seed_container(ContainerInfo.model_validate({
        "id": "cid-1", "name": "api", "image": "nginx:alpine",
        "status": ContainerStatus.RUNNING,
        "created_at": "2026-04-01T12:00:00+00:00",
        "labels": {"vela.project_id": str(seeded_user.personal_project_id)},
        "ports": [],
    }))
    url = "/api/containers/cid-1/ws-ticket?purpose=logs"
    assert anonymous_client.post(url).status_code == 401
    assert api_client.post(url).status_code == 200


def test_login_throttled(anonymous_client: TestClient) -> None:
    rate_limit.reset_for_tests()
    for _ in range(11):
        response = anonymous_client.post(
            "/api/auth/login", json={"email": "nobody@example.test", "password": "wrong-password"}
        )
    assert response.status_code == 429
```
(Add `issuer: str` and `audience: str` fields to the expected `AccessTokenClaims` — the test drives the implementation.)

- [ ] **Step 2: Run test to verify it fails** — `cd backend; python -m pytest tests/test_auth_hardening.py -q`. Expected: import errors for `rate_limit` / `ws_tickets`, missing `issuer`/`audience`, and 404 on the ticket endpoint.

- [ ] **Step 3: Write minimal implementation** — `backend/app/core/auth/rate_limit.py`:
```python
"""In-process sliding-window limiter for unauthenticated endpoints."""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request, status

_WINDOW_SECONDS = 300.0
_MAX_ATTEMPTS = 10
_buckets: dict[str, Deque[float]] = defaultdict(deque)


def client_identity(request: Request) -> str:
    """Prefer a forwarded client only when the peer is an allowed proxy."""
    peer = request.client.host if request.client else "unknown"
    allowed = {
        value.strip()
        for value in os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1").split(",")
        if value.strip()
    }
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded if peer in allowed and forwarded else peer


def check_rate_limit(key: str) -> None:
    now = time.monotonic()
    bucket = _buckets[key]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
        )
    bucket.append(now)


def reset_for_tests() -> None:
    _buckets.clear()
```
Add `# ponytail: per-process limiter; use a shared store if multiple workers are deployed.` as a module comment.

`backend/app/core/auth/ws_tickets.py`:
```python
"""Short-lived, single-use tickets for WebSocket authentication."""
from __future__ import annotations

import secrets
import time
import uuid

_TICKET_TTL_SECONDS = 60.0
_tickets: dict[str, tuple[uuid.UUID, str, str, float]] = {}


def issue_ws_ticket(user_id: uuid.UUID, container_id: str, purpose: str) -> str:
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (user_id, container_id, purpose, time.monotonic() + _TICKET_TTL_SECONDS)
    return ticket


def consume_ws_ticket(ticket: str, container_id: str, purpose: str) -> uuid.UUID | None:
    entry = _tickets.pop(ticket, None)
    if entry is None:
        return None
    user_id, expected_container, expected_purpose, expires_at = entry
    if time.monotonic() > expires_at:
        return None
    if (expected_container, expected_purpose) != (container_id, purpose):
        return None
    return user_id


def reset_for_tests() -> None:
    _tickets.clear()
```
`backend/tests/conftest.py`: add an autouse fixture so the process-global buckets cannot leak between tests — without it, the ~10 existing `POST /api/tokens/` calls in `test_api_tokens.py`, `test_exec_websocket.py:307` and the new `test_token_lifecycle.py:783` would hit the 11th-attempt 429 from `create_token`'s limiter:
```python
@pytest.fixture(autouse=True)
def reset_in_process_auth_state() -> None:
    from app.core.auth import rate_limit, ws_tickets

    rate_limit.reset_for_tests()
    ws_tickets.reset_for_tests()
```
(The import is intentionally lazy: conftest sets env vars before importing `app`.)

`backend/app/core/auth/tokens.py`: add `issuer: str` / `audience: str` to `AccessTokenClaims`, constants `_ISSUER = "vela"`, `_AUDIENCE = "vela-api"`, add `"iss": _ISSUER, "aud": _AUDIENCE` to the payload, decode with `jwt.decode(token, _secret(), algorithms=[_ALGORITHM], issuer=_ISSUER, audience=_AUDIENCE)`, and return the two new fields. (Single configured audience per deployment, per spec.)

`backend/app/api/routes/auth.py`: import `Request`, `check_rate_limit`, `client_identity`. Add `request: Request` to `login` and call `check_rate_limit(client_identity(request))` before `authenticate`. Add `request: Request` to `clerk_exchange` and call the same. `clerk_exchange` must also fail closed when origins are unconfigured — that is handled in `clerk.py`.

`backend/app/api/routes/tokens.py`: add `request: Request`, `check_rate_limit(client_identity(request))` in `create_token`.

`backend/app/core/oauth/clerk.py`: replace `_warn_if_azp_unenforced` with a hard failure at verification time. In `verify_clerk_token`, after `allowed_origins = _allowed_origins()`:
```python
    if not allowed_origins:
        raise IntegrationConfigurationError(
            "VELA_ALLOWED_ORIGINS must be set when Clerk is enabled."
        )
    azp = payload.get("azp")
    if not isinstance(azp, str) or azp not in allowed_origins:
        raise ClerkTokenError("Clerk token azp is not an allowed origin.")
```
Delete `_azp_warning_logged`, `_warn_if_azp_unenforced` and the `_warn_if_azp_unenforced()` call. In `frontend/playwright.config.ts` add `VELA_ALLOWED_ORIGINS: 'http://127.0.0.1:5173'` to `e2eApiEnv` so E2E fixtures are valid when Clerk is enabled in a future test.

`backend/app/api/routes/containers.py`: add the ticket endpoint using the existing access check:
```python
@router.post("/{container_id}/ws-ticket")
async def issue_container_ws_ticket(
    container_id: str,
    purpose: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> dict[str, str]:
    """Issue a short-lived single-use ticket for a logs/exec WebSocket."""
    if purpose not in ("logs", "exec"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid WebSocket purpose.")
    await require_container_access(
        session, orchestrator, current_user, container_id,
        action="read" if purpose == "logs" else "write",
    )
    return {"ticket": issue_ws_ticket(current_user.id, container_id, purpose)}
```
In both `container_logs_stream` and `container_exec_ws`, replace the `access_token` query lookup and move authentication **before** `await websocket.accept()`:
```python
    ticket = websocket.query_params.get("ticket", "")
    try:
        user_id = consume_ws_ticket(ticket, container_id, "logs")  # "exec" in the exec handler
    except Exception:
        user_id = None
    if user_id is None:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    user = await get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    try:
        await require_container_access(session, orchestrator, user, container_id, action="read")
    except (ContainerNotFoundError, ProjectAccessDeniedError):
        await websocket.close(code=1008, reason="Unauthorized")
        return
    await websocket.accept()
```
Keep the remaining stream/exec logic unchanged. `_get_websocket_user` becomes unused — delete it. Note the `HTTPException` import is needed in `containers.py`.

- [ ] **Step 4: Run test to verify it passes** — `cd backend; python -m pytest tests/test_auth_hardening.py -q`. Expected: `5 passed`. Then full backend gate. **Merge note:** `fix/security-and-cli-hardening` already has an inline `_check_login_rate_limit` in `auth.py` (commit `35f0db9`); when merged, resolve by deleting the inline version and calling `check_rate_limit(client_identity(request))`.

- [ ] **Step 5: Commit** — `git add backend/app/core/auth/rate_limit.py backend/app/core/auth/ws_tickets.py backend/app/api/routes/auth.py backend/app/api/routes/tokens.py backend/app/core/oauth/clerk.py backend/app/core/auth/tokens.py backend/app/api/routes/containers.py backend/tests/conftest.py frontend/playwright.config.ts backend/tests/test_auth_hardening.py && git commit -m "fix(auth): throttle, fail-closed Clerk, iss/aud JWTs, single-use WS tickets"`

---

### Task 8: Git URL SSRF guard and outbound config docs (F10)

**Files:**
- Modify: `backend/app/core/security/outbound_url.py:10-53`, `backend/app/core/git/git_ops.py:12-46`, `README.md` (env var line only)
- Test: `backend/tests/test_git_url_guard.py`

**Interfaces:**
- Consumes: `CloneError` from `app/core/exceptions.py`; `e2e_git_shallow_clone_if_enabled` hook must remain first in `git_shallow_clone`.
- Produces: `validate_git_remote(url: str) -> str` in `core/security/outbound_url.py`; `allow_private_env` parameter on `validate_outbound_url`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_git_url_guard.py`:
```python
import pytest

from app.core.exceptions import CloneError
from app.core.git.git_ops import git_head_ref, git_shallow_clone
from app.core.security.outbound_url import validate_git_remote


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://169.254.169.254/latest/meta-data/",
    "https://127.0.0.1/x.git",
])
def test_public_git_remote_rejects_private_or_local_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_git_remote(url)


@pytest.mark.asyncio
async def test_clone_rejects_file_scheme(tmp_path) -> None:
    with pytest.raises(CloneError):
        await git_shallow_clone(url="file:///etc/passwd", branch="main", dest=tmp_path / "x")


def test_opt_in_allows_private_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("VELA_GIT_ALLOW_PRIVATE_ENDPOINTS", "1")
    assert validate_git_remote("http://127.0.0.1/x.git") == "http://127.0.0.1/x.git"
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend; python -m pytest tests/test_git_url_guard.py -q`. Expected: `ImportError` for `validate_git_remote`; clone test fails because `file://` reaches the e2e hook / clone command.

- [ ] **Step 3: Write minimal implementation** — in `backend/app/core/security/outbound_url.py`:
```python
def allow_private_endpoints(*, env: str = ALLOW_PRIVATE_ENV) -> bool:
    return os.environ.get(env, "").strip() == "1"


def validate_outbound_url(
    url: str, *, label: str = "Base URL", allow_private_env: str = ALLOW_PRIVATE_ENV
) -> str:
    if allow_private_endpoints(env=allow_private_env):
        return url
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError(f"{label} must start with https://.")
    host = parts.hostname
    if not host:
        raise ValueError(f"{label} must include a host.")
    # ponytail: sync DNS in the request validator; fine at this call rate.
    if not _host_is_public(host):
        raise ValueError(f"{label} must resolve to a public address.")
    return url


def validate_git_remote(url: str) -> str:
    """Apply the outbound SSRF guard to Git clone URLs (SSH remotes use host checks)."""
    from urllib.parse import urlsplit

    stripped = url.strip()
    lowered = stripped.lower()
    if lowered.startswith("git@"):
        host = stripped.split("@", 1)[1].split(":", 1)[0]
    elif lowered.startswith(("ssh://", "git://")):
        host = urlsplit(stripped).hostname or ""
    elif lowered.startswith(("http://", "https://")):
        if not allow_private_endpoints(env="VELA_GIT_ALLOW_PRIVATE_ENDPOINTS"):
            return validate_outbound_url(
                stripped, label="Git URL",
                allow_private_env="VELA_GIT_ALLOW_PRIVATE_ENDPOINTS",
            )
        return stripped
    else:
        raise ValueError("Git URL must be an http(s), ssh, git:// or git@ remote.")
    if not host:
        raise ValueError("Git URL must include a host.")
    if not allow_private_endpoints(env="VELA_GIT_ALLOW_PRIVATE_ENDPOINTS") and not _host_is_public(host):
        raise ValueError("Git URL must resolve to a public address.")
    return stripped
```
In `backend/app/core/git/git_ops.py`, import `validate_git_remote` and add the guard in both transports:
```python
from app.core.security.outbound_url import validate_git_remote

def _guard_git_url(url: str) -> None:
    from app.core.exceptions import CloneError

    try:
        validate_git_remote(url)
    except ValueError as exc:
        raise CloneError(url, str(exc)) from exc
```
Call `_guard_git_url(url)` in `git_shallow_clone` immediately after the e2e hook and in `git_head_ref` before building the command. Add to README's env table:
```
| `VELA_GIT_ALLOW_PRIVATE_ENDPOINTS` | Set `1` to allow private/LAN Git remotes (mirrors `VELA_LLM_ALLOW_PRIVATE_ENDPOINTS`). Off by default. |
```

- [ ] **Step 4: Run test to verify it passes** — `cd backend; python -m pytest tests/test_git_url_guard.py -q`. Expected: `5 passed`. Then full backend gate. **Merge note:** `fix/security-and-cli-hardening` adds `_validate_git_url` scheme checks in `git_ops.py` (`35f0db9`); resolve by keeping that function but delegating its body to `validate_git_remote`.

- [ ] **Step 5: Commit** — `git add backend/app/core/security/outbound_url.py backend/app/core/git/git_ops.py backend/tests/test_git_url_guard.py README.md && git commit -m "fix(git): apply outbound SSRF guard to Git remotes"`

---

### Task 9: Backend cleanup — instructor audit, LLM cache key, duplicate constant, log WS timeout, scaling write auth (F9, F18, F19, F20, F21, F26)

**Files:**
- Modify: `backend/app/api/routes/projects.py:293-415`, `backend/app/core/git/git_source_analysis.py:801-810`, `backend/app/core/stacks/repo_analysis.py:366-373`, `backend/app/core/llm/provider.py:7-12`, `backend/app/api/routes/containers.py:1361-1408`, `backend/app/api/routes/scaling.py:24-97`
- Test: `backend/tests/test_backend_cleanup.py`

**Interfaces:**
- Consumes: `emit_audit_log`; `_require_accessible_container_name` (`scaling.py:24`); `_exec_max_session_seconds()` (`containers.py:178`).
- Produces: `require_container_write_access` helper in `scaling.py`; `cache_identity(user_id: uuid.UUID | None, config: LlmConfig, repo_ref: str) -> str` in `core/llm/cache.py`; `user_id` folded into `cache_version` at both call sites.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_backend_cleanup.py`:
```python
import uuid

from fastapi.testclient import TestClient

from app.api.routes.scaling import update_scaling_policy
from app.core.llm.cache import cache_identity
from app.core.llm.provider import DEFAULT_LLM_MODEL


def test_single_default_llm_model() -> None:
    assert DEFAULT_LLM_MODEL == "gemini-3.1-flash-lite"


def test_cache_identity_separates_users_and_repos() -> None:
    user = uuid.uuid4()
    from app.core.llm.provider import LlmConfig

    config = LlmConfig(
        provider="gemini", url="https://example.test", headers={},
        params={}, model="m",
    )
    assert cache_identity(user, config, "repo-a") != cache_identity(user, config, "repo-b")
    assert cache_identity(user, config, "repo-a") != cache_identity(uuid.uuid4(), config, "repo-a")


def test_viewer_cannot_update_scaling_policy(
    api_client: TestClient, seeded_user, seeded_other_user, fake_orchestrator,
    db_session_factory,
) -> None:
    import asyncio

    from app.core.auth.tokens import create_access_token
    from app.core.models import ContainerInfo, ContainerStatus
    from app.db.models import ProjectMembership

    async def prepare() -> None:
        async with db_session_factory() as session:
            session.add(ProjectMembership(
                project_id=seeded_user.personal_project_id,
                user_id=seeded_other_user.id, role="viewer",
            ))
            await session.commit()

    asyncio.run(prepare())
    fake_orchestrator.seed_container(ContainerInfo.model_validate({
        "id": "scale-cid", "name": "api", "image": "nginx",
        "status": ContainerStatus.RUNNING, "created_at": "2026-04-01T12:00:00+00:00",
        "labels": {"vela.project_id": str(seeded_user.personal_project_id)},
        "ports": [],
    }))

    api_client.headers["Authorization"] = f"Bearer {create_access_token(seeded_other_user.id)}"
    response = api_client.put("/api/scaling/policies/api", json={"enabled": True})
    assert response.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails** — `cd backend; python -m pytest tests/test_backend_cleanup.py -q`. Expected: `ImportError` for `cache_identity`; scaling PUT returns 200 for a viewer.

- [ ] **Step 3: Write minimal implementation** — remove the first duplicate `DEFAULT_LLM_MODEL = "gemini-3.5-flash-lite"` at `backend/app/core/llm/provider.py:7` (keep line 12, `gemini-3.1-flash-lite`).

In `backend/app/core/llm/cache.py` add:
```python
import hashlib

def cache_identity(user_id: uuid.UUID | None, config: object, repo_ref: str) -> str:
    """Stable discriminator so users, providers and repos never share a cached analysis."""
    provider = getattr(config, "provider", "unknown")
    model = getattr(config, "model", "unknown")
    base = getattr(config, "base_url", None) or getattr(config, "url", "")
    fingerprint = hashlib.sha256(
        f"{provider}:{model}:{base}".encode("utf-8")
    ).hexdigest()[:12]
    return f"{user_id or 'server'}:{fingerprint}:{repo_ref}"
```
(add `import uuid`.) At `git_source_analysis.py:801-804` append `:{user_id}` to `cache_version`; at `repo_analysis.py:366-369` replace the version construction with `cache_version = cache_identity(user_id, config, git_url)` and import `cache_identity`. Both functions already accept `user_id`.

In `backend/app/api/routes/scaling.py`, add a write-access helper and use it only in `update_scaling_policy`:
```python
from app.core.projects.access import list_accessible_project_ids, require_container_access
from app.core.projects.enums import can_write
from app.db.models import User

async def require_container_write_access(
    session: AsyncSession,
    orchestrator: ContainerOrchestrator,
    current_user: User,
    container_name: str,
) -> None:
    """Reject callers who can only view the container."""
    info = await orchestrator.get_by_name(container_name) if hasattr(
        orchestrator, "get_by_name"
    ) else next(
        (c for c in await orchestrator.list(user_id=current_user.id) if c.name == container_name),
        None,
    )
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Container not found.")
    await require_container_access(
        session, orchestrator, current_user, info.id, action="write"
    )
```
Call `await require_container_write_access(session, orchestrator, current_user, container_name)` in `update_scaling_policy` immediately after `_require_accessible_container_name`.

In `backend/app/api/routes/containers.py`, wrap the log-stream loop so it respects the same session cap as exec:
```python
    try:
        await asyncio.wait_for(
            _stream_logs_to_websocket(websocket, orchestrator, container_id, tail_parsed, follow_logs),
            timeout=_exec_max_session_seconds(),
        )
    except TimeoutError:
        with suppress(Exception):
            await websocket.send_text("[session expired]")
            await websocket.close(code=1000, reason="Session timeout")
```
and extract the existing `async for` body into that helper. 

In `backend/app/api/routes/projects.py`, add `emit_audit_log` to the four instructor mutation handlers (`patch_project_member` ~:297, `delete_project_member` ~:323, `create_project_invitation` ~:376, `delete_project_invitation` ~:402) immediately before their existing `session.commit()`, e.g.:
```python
    await emit_audit_log(
        session, user_id=current_user.id, action="project.member_role_changed",
        target_type="project", target_id=str(project_id),
        details={"changed_user_id": str(member_user_id)},
    )
```
Use actions `project.member_role_changed`, `project.member_removed`, `project.invitation_created`, `project.invitation_cancelled`. Keep the existing `require_instructor` gate. README gets one sentence: "Instructors may manage members and invitations across projects; every such mutation is recorded in the audit log."

- [ ] **Step 4: Run test to verify it passes** — `cd backend; python -m pytest tests/test_backend_cleanup.py -q`. Expected: `3 passed`. Then full backend gate.

- [ ] **Step 5: Commit** — `git add backend/app/api/routes/projects.py backend/app/core/git/git_source_analysis.py backend/app/core/stacks/repo_analysis.py backend/app/core/llm/cache.py backend/app/core/llm/provider.py backend/app/api/routes/containers.py backend/app/api/routes/scaling.py README.md backend/tests/test_backend_cleanup.py && git commit -m "fix(backend): audit instructor actions, scope LLM cache, enforce scaling write access"`

---

### Task 10: Frontend correctness — error mapper, dates, locales, timers, pinned Clerk, history refresh (H1, H2, M1, M13, L2, L3, L6, L10, L14)

**Files:**
- Create: `frontend/e2e/api-errors.spec.ts`
- Modify: `frontend/src/api/core.ts:141-165`, `frontend/src/pages/AuditLogPage.tsx:95,155-166,307`, `frontend/src/pages/admin/AuditPanel.tsx:12-14`, `frontend/src/pages/LogsPage.tsx:107,132,294`, `frontend/src/pages/LoginPage.tsx:6-14,86-104`, `frontend/src/pages/stacks/StackBuilderPage.tsx:185,368`, `frontend/src/pages/DashboardPage.tsx:22,35-88,119`, `frontend/src/components/charts/MetricChart.tsx:61,115`
- Test: `frontend/e2e/api-errors.spec.ts`

**Interfaces:**
- Consumes: `ApiError` / `formatApiError(error, locale?)` from `core.ts:80,142`; `useSearchParams` from react-router-dom.
- Produces: `formatApiError` always returns a `string`; date filters sent as `YYYY-MM-DD`; explicit `en-US` locale formatters; exported `CLERK_JS_VERSION`, `clerkBrowserScriptUrl(frontendApi)` and `safeNextPath(rawNext)` from `LoginPage.tsx`; one cancellable highlight timer in `StackBuilderPage`; `historyRefreshSignal` incremented after Dashboard row mutations.

- [ ] **Step 1: Write the failing test** — `frontend/e2e/api-errors.spec.ts`:
```ts
import { expect, test } from '@playwright/test'
import { ApiError, formatApiError } from '../src/api/core'
import { clerkBrowserScriptUrl, safeNextPath } from '../src/pages/LoginPage'

test('formatApiError never returns a non-string detail from a 422 body', () => {
  const error = new ApiError(
    'Request failed: 422',
    422,
    JSON.stringify({ detail: [{ loc: ['body', 'name'], msg: 'field required' }] }),
  )
  const message = formatApiError(error)
  expect(typeof message).toBe('string')
  expect(message).not.toContain('[object Object]')
})

test('Clerk browser script URL is pinned to an exact version', () => {
  const url = clerkBrowserScriptUrl('clerk.example.com')
  expect(url).not.toContain('@latest')
  expect(url).toMatch(/@clerk\/clerk-js@\d+\.\d+\.\d+\/dist\/clerk\.browser\.js$/)
})

test('safeNextPath rejects protocol-relative redirects', () => {
  expect(safeNextPath('//evil.test/x')).toBe('/containers')
  expect(safeNextPath('/containers')).toBe('/containers')
})
```

- [ ] **Step 2: Run test to verify it fails** — `cd frontend; npm run test:e2e -- e2e/api-errors.spec.ts`. Expected: `formatApiError` returns the `detail` array (`typeof message === 'object'`); `clerkBrowserScriptUrl` is not exported; `safeNextPath('//evil.test/x')` returns `//evil.test/x`.

- [ ] **Step 3: Write minimal implementation** — in `frontend/src/api/core.ts:157`:
```ts
    const detail =
      typeof parsed.detail === 'string'
        ? parsed.detail
        : error.message
```
In `frontend/src/pages/AuditLogPage.tsx:159-165` send plain date strings instead of local-midnight UTC conversion:
```ts
      if (fromRaw) params.from_date = fromRaw
      if (toRaw) params.to_date = toRaw
```
(replace the `new Date(\`${fromRaw}T00:00:00\`).toISOString()` / `T23:59:59` blocks and delete the now-unused local variables.)
In `frontend/src/pages/LogsPage.tsx:132`, export the same search the table displays: `await exportLogs(buildParams(false, debouncedSearch))` (the table fetches with `debouncedSearch` at line 107; using raw `search` at 132 makes the CSV disagree with the view — M13).
Use an explicit locale for **all** displayed timestamps (L10):
- `AuditPanel.tsx:12-14`: `const formatter = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', hour12: false }); return formatter.format(new Date(value))`
- `AuditLogPage.tsx:307` and `LogsPage.tsx:294`: replace `.toLocaleString([], { hour12: false })` with `new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'medium', hour12: false }).format(new Date(...))`.
- `AuditLogPage.tsx:95`: replace `date.toLocaleDateString([], {...})` with `new Intl.DateTimeFormat('en-US', { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' }).format(date)`.
- `MetricChart.tsx:61` / `:115`: `new Intl.DateTimeFormat('en-US', { hour: '2-digit', minute: '2-digit' }).format(d)` and `new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(String(label)))`.

In `frontend/src/pages/LoginPage.tsx`:
- Export `safeNextPath` and reject protocol-relative paths at lines 6-14: after decoding, `return decoded.startsWith('/') && !decoded.startsWith('//') ? decoded : '/containers'`.
- Pin the browser script (H2) and make it removable (L3). Add at module scope, replacing the inline URL at line 93:
```ts
export const CLERK_JS_VERSION = '5.97.0'
export function clerkBrowserScriptUrl(frontendApi: string): string {
  return `https://${frontendApi}/npm/@clerk/clerk-js@${CLERK_JS_VERSION}/dist/clerk.browser.js`
}
```
Use `script.src = clerkBrowserScriptUrl(clerkConfig.frontendApi)`. Set `CLERK_JS_VERSION` to the exact validated Clerk JS release available at implementation time (the value above is the concrete planned pin); never a tag, range or `@latest` — bump it explicitly. In the effect at lines 83-104, keep a `let injectedScript: HTMLScriptElement | null = null`, assign it before `appendChild`, and add a cleanup that sets `cancelled = true`, calls `injectedScript?.remove()` and resets `clerkLoadPromise.current = null`. The effect's dependency array stays `[clerkConfig, ...]` with no new deps.

In `frontend/src/pages/stacks/StackBuilderPage.tsx` (L6): add `const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null)`, a `useEffect(() => () => { if (highlightTimer.current !== null) clearTimeout(highlightTimer.current) }, [])`, and a `scheduleHighlight(index)` helper that clears any prior timer before setting a new 2s timer which also nulls the ref. Replace the bare `setTimeout(...)` at line 185 and `window.setTimeout(...)` at line 368 with `scheduleHighlight(newIndex)` / `scheduleHighlight(nextIndex)`.

In `frontend/src/pages/DashboardPage.tsx` (L14): after each successful `await refresh()` in `onStart` (line 41), `onStop` (line 57) and `onConfirmRemove` (line 80), add `setHistoryRefreshSignal((signal) => signal + 1)` so the deployment history (`DeploymentHistorySection` at line 120) reflects row operations instead of only the manual Refresh button.

- [ ] **Step 4: Run test to verify it passes** — `cd frontend; npm run test:e2e -- e2e/api-errors.spec.ts`. Expected: `3 passed`. Then full frontend gate (`npm run build`, `npm run lint`, `npm run typecheck`, `npm run test:e2e`) and the backend gate (API contract unchanged).

- [ ] **Step 5: Commit** — `git add frontend/src/api/core.ts frontend/src/pages/AuditLogPage.tsx frontend/src/pages/admin/AuditPanel.tsx frontend/src/pages/LogsPage.tsx frontend/src/pages/LoginPage.tsx frontend/src/pages/stacks/StackBuilderPage.tsx frontend/src/pages/DashboardPage.tsx frontend/src/components/charts/MetricChart.tsx frontend/e2e/api-errors.spec.ts && git commit -m "fix(frontend): string-only API errors, plain dates, explicit locales, pinned Clerk, timer cleanup, history refresh"`

---

### Task 11: Frontend a11y and UX — dialogs, guards, tabs, links, live regions, labels (H3, M2–M5, M11, M12, L1, L4, L5, L11, L12)

**Files:**
- Modify: `frontend/src/pages/StacksPage.tsx`, `frontend/src/components/DockerfileTemplatesSection.tsx`, `frontend/src/components/Layout.tsx`, `frontend/src/components/UserMenu.tsx`, `frontend/src/pages/AdminPage.tsx`, `frontend/src/pages/stacks/StackBuilderPage.tsx`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/TeamsPage.tsx`, `frontend/src/pages/ResourceDashboardPage.tsx`, `frontend/src/pages/SettingsPage.tsx`, `frontend/src/auth/RequireAuth.tsx`, `frontend/src/pages/settings/LlmProviderCard.tsx`, `frontend/src/components/workloads/WorkloadsTable.tsx`, `frontend/src/index.css`
- Test: `frontend/e2e/a11y.spec.ts`

**Interfaces:**
- Consumes: `ConfirmDialog` from `frontend/src/components/ConfirmDialog.tsx`; `useBlocker` / router navigation guard from react-router-dom 7.14.0; `useTheme`.
- Produces: skip link + `<main id="main-content" tabIndex={-1}>`; `Link`-based account menu; arrow-key tablist in `AdminPage`; `beforeunload` + route blocker in `StackBuilderPage`.

- [ ] **Step 1: Write the failing test** — `frontend/e2e/a11y.spec.ts`:
```ts
import { E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD } from './constants'
import { expect, loginAndSeedToken, test } from './fixtures'

test('layout exposes a skip link to the main landmark', async ({ authenticatedPage: page }) => {
  const skip = page.getByRole('link', { name: /skip to main content/i })
  await expect(skip).toBeVisible()
  await skip.focus()
  await skip.press('Enter')
  await expect(page.locator('main#main-content')).toBeFocused()
})

test('admin tabs support arrow keys', async ({ page }) => {
  await loginAndSeedToken(page, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
  await page.goto('/admin')
  const usersTab = page.getByRole('tab', { name: 'Users' })
  await usersTab.focus()
  await usersTab.press('ArrowRight')
  await expect(page.getByRole('tab', { name: 'Audit' })).toHaveAttribute('aria-selected', 'true')
})
```

- [ ] **Step 2: Run test to verify it fails** — `cd frontend; npm run test:e2e -- e2e/a11y.spec.ts`. Expected: both tests fail (no skip link; ArrowRight does not switch tabs).

- [ ] **Step 3: Write minimal implementation** — `frontend/src/components/Layout.tsx`:
```tsx
export default function Layout() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <Navbar />
      <main id="main-content" className="main-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  )
}
```
Add `.skip-link` styles in `frontend/src/index.css` using only existing tokens (`position: absolute; left: -9999px;` and on `:focus` `left: var(--space-md); top: var(--space-sm); z-index: 100; background: var(--surface); color: var(--text); padding: var(--space-sm);` — substitute the actual token names present in `:root`).

`frontend/src/components/UserMenu.tsx`: import `{ Link }` from `react-router-dom`; replace the two navigation `<button>` elements (lines 75-90) with `<Link to="/settings" className="user-menu__item" onClick={() => setOpen(false)}>` and `<Link to="/audit" ...>`; keep the Log out `<button>` and the icon `aria-hidden` markers.

`frontend/src/pages/AdminPage.tsx`: add arrow-key support to the tablist:
```tsx
  const tabs: AdminTab[] = canViewAudit ? ['users', 'audit'] : ['users']

  function onTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const index = tabs.indexOf(activeTab)
    const delta = event.key === 'ArrowRight' ? 1 : -1
    const next = tabs[(index + delta + tabs.length) % tabs.length]
    setActiveTab(next)
    document.getElementById(`admin-${next}-tab`)?.focus()
  }
```
add `id="admin-users-tab"` / `id="admin-audit-tab"` and `tabIndex={activeTab === 'users' ? 0 : -1}` to the two tab buttons plus `onKeyDown={onTabKeyDown}`; also add `aria-labelledby="admin-users-tab"` / `aria-labelledby="admin-audit-tab"` to the matching `role="tabpanel"` elements (M4).

`frontend/src/pages/StacksPage.tsx` and `frontend/src/components/DockerfileTemplatesSection.tsx` (the real path — imported as a component by `BuilderPage.tsx:4` and `ImagesPage.tsx:4`; there is no `pages/DockerfileTemplatesSection.tsx`): replace the hand-rolled confirm `window.confirm` / two-click "Confirm?" button for stack deletion (`StacksPage.tsx:142-149,350-370`) and template deletion with the shared `<ConfirmDialog>` (props per `ConfirmDialog.tsx`: `open`, `title`, `message`, `confirmLabel`, `onConfirm`, `onCancel`). Ensure destructive actions are behind confirmation.

`frontend/src/pages/stacks/StackBuilderPage.tsx`: guard unsaved navigation:
```tsx
import { useBlocker } from 'react-router-dom'
const blocker = useBlocker(({ currentLocation, nextLocation }) =>
  isDirty && currentLocation.pathname !== nextLocation.pathname,
)
useEffect(() => {
  if (blocker.state !== 'blocked') return
  if (window.confirm('Discard unsaved stack changes?')) blocker.proceed()
  else blocker.reset()
}, [blocker])
```
(Keep the `window.confirm` here only as the explicit destructive confirmation — it is not an inline form explanation.)

Remaining a11y/UX findings, all with concrete edits (no unbounded sweeps, no new colors/radii/shadows):
- **M11** `frontend/src/pages/StacksPage.tsx:396`: change the success banner role to `role={tone === 'err' ? 'alert' : 'status'}` so deploy/delete confirmations are announced.
- **M12** `frontend/src/pages/stacks/StackBuilderPage.tsx:278,383-390`: change `<form onSubmit={(e) => e.preventDefault()}>` to `onSubmit={(e) => { e.preventDefault(); void handleSave() }}` and change the Save button at `:383` from `type="button"` + `onClick={handleSave}` to `type="submit"` (drop the onClick) so Enter in the name field saves.
- **L1** `frontend/src/pages/LoginPage.tsx:173-195` and `frontend/src/pages/TeamsPage.tsx:86-95`: add `name="email"`/`autoComplete="username"`, `name="password"`/`autoComplete="current-password"`, and `name="team_name"` to the respective inputs.
- **L4** `frontend/src/pages/ResourceDashboardPage.tsx:85-92`: add `aria-pressed={timeRange === range}` to each time-range button.
- **L5** replace every plain "Loading…" with the existing shared `<Skeleton>` from `frontend/src/components/Skeleton.tsx` using an existing token class (e.g. `className="skeleton--hint-line"`): `StackBuilderPage.tsx:309`, `SettingsPage.tsx:193-194`, `frontend/src/auth/RequireAuth.tsx:16`, `frontend/src/pages/settings/LlmProviderCard.tsx:201`.
- **L11** `frontend/src/components/workloads/WorkloadsTable.tsx:61-70`: remove `aria-label` from the `<select>` because the adjacent `<label htmlFor>` already names it (the duplicate aria-label wins for screen readers).
- **L12** `frontend/src/pages/SettingsPage.tsx:425`: change `busy ? 'Working…' : 'Disconnect'` to `busy ? 'Disconnecting…' : 'Disconnect'`.

- [ ] **Step 4: Run test to verify it passes** — `cd frontend; npm run test:e2e -- e2e/a11y.spec.ts`. Expected: `2 passed`. Then full frontend gate.

- [ ] **Step 5: Commit** — `git add frontend/src/components/Layout.tsx frontend/src/components/UserMenu.tsx frontend/src/pages/AdminPage.tsx frontend/src/pages/StacksPage.tsx frontend/src/components/DockerfileTemplatesSection.tsx frontend/src/pages/stacks/StackBuilderPage.tsx frontend/src/pages/LoginPage.tsx frontend/src/pages/TeamsPage.tsx frontend/src/pages/ResourceDashboardPage.tsx frontend/src/pages/SettingsPage.tsx frontend/src/auth/RequireAuth.tsx frontend/src/pages/settings/LlmProviderCard.tsx frontend/src/components/workloads/WorkloadsTable.tsx frontend/src/index.css frontend/e2e/a11y.spec.ts && git commit -m "fix(frontend): skip link, labelled main, keyboard tabs, route guard, confirmations, form a11y"`

---

### Task 12: Frontend structure and consistency — polls, WS tickets, dedup, theme, copy, dead code (M6–M10, M14, M15, L7–L9, L15–L17)

**Files:**
- Create: `frontend/src/pages/SourceWorkspacePage.tsx`, `frontend/src/pages/source-page.css`
- Modify: `frontend/src/api/containers.ts:145-214`, `frontend/src/components/workloads/ContainerLogPanel.tsx:96-108`, `frontend/src/components/workloads/ContainerTerminal.tsx:27-41`, `frontend/src/hooks/useTheme.ts:18-31`, `frontend/index.html:7`, `frontend/src/pages/Home.tsx:22-36`, `frontend/src/pages/ImagesPage.tsx`, `frontend/src/pages/BuilderPage.tsx`, `frontend/src/pages/AdminPage.tsx`, `frontend/src/pages/ResourceDashboardPage.tsx`, `frontend/src/pages/ContainersPage.tsx`, `frontend/src/App.tsx:12-19,64-79`, `frontend/src/pages/PlaceholderPage.tsx` (delete), `frontend/src/api/client.ts`, `frontend/src/pages/containers/BuildConfigModal.tsx`, `frontend/e2e/api-helpers.ts` (JSDoc cleanup only)
- Test: `frontend/e2e/structure.spec.ts`

**Interfaces:**
- Consumes: Task 7's `POST /api/containers/{id}/ws-ticket?purpose=logs|exec` → `{"ticket": string}`; `apiPost` from `frontend/src/api/core.ts`.
- Produces: `issueWsTicket(containerId, purpose): Promise<string>` in `api/containers.ts`; `SourceWorkspacePage` shared by `/images` and `/builder`.

- [ ] **Step 1: Write the failing test** — `frontend/e2e/structure.spec.ts`:
```ts
import { deployImageContainer } from './api-helpers'
import { expect, test } from './fixtures'

test('home copy is English and theme-color follows the theme', async ({ authenticatedPage: page }) => {
  await page.goto('/')
  await expect(page.locator('.hero__eyebrow')).toHaveText('Deployment platform')
  const initial = await page.locator('meta[name="theme-color"]').getAttribute('content')
  await page.getByRole('button', { name: /toggle color theme/i }).click()
  await expect(page.locator('meta[name="theme-color"]')).not.toHaveAttribute('content', initial ?? '')
})

test('logs and exec WebSockets use a ticket, never access_token', async ({ authenticatedPage: page }) => {
  // Seed a running container through the existing E2E API helper — the fresh
  // /containers page has no container, so there would be no terminal button.
  const containerName = `ws-ticket-${Date.now()}`
  const deployed = await deployImageContainer(page, 'nginx:alpine', containerName)
  expect(deployed.ok()).toBeTruthy()
  const urls: string[] = []
  page.on('websocket', (socket) => urls.push(socket.url()))
  await page.goto('/containers')
  const row = page.locator('table.workloads-table tbody tr').filter({
    has: page.getByRole('cell', { name: containerName, exact: true }),
  })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: /terminal/i }).click()
  await expect.poll(() => urls.some((url) => url.includes('ticket='))).toBe(true)
  expect(urls.some((url) => url.includes('access_token='))).toBe(false)
})
```

- [ ] **Step 2: Run test to verify it fails** — `cd frontend; npm run test:e2e -- e2e/structure.spec.ts`. Expected: home copy assertion fails; with the seeded container the WS URL still contains `access_token=` instead of `ticket=`.

- [ ] **Step 3: Write minimal implementation** — in `frontend/src/api/containers.ts`:
```ts
import { apiPost } from './core'

export async function issueWsTicket(
  containerId: string,
  purpose: 'logs' | 'exec',
): Promise<string> {
  const response = await apiPost<{ ticket: string }>(
    `/api/containers/${encodeURIComponent(containerId)}/ws-ticket?purpose=${purpose}`,
    {},
  )
  return response.ticket
}
```
Make `openContainerLogWebSocket` and `openContainerExecWebSocket` `async`, replace `getAccessToken()` with `await issueWsTicket(containerId, 'logs'|'exec')`, and build params with `{ ticket, tail, follow }` / `{ ticket }`. Update callers: `ContainerLogPanel.tsx` wrap creation in `void (async () => { ... })()` inside its effect (keep the existing error banner on rejection); `ContainerTerminal.tsx` create the socket asynchronously and guard with a `disposed` flag before using `execWs`.

`ContainerTerminal.tsx` lifecycle fix (L8): the early `if (!containerRef.current) return` at `:27` currently skips `term.dispose()` / `fit.dispose()`; change it to dispose both before returning. Likewise, if the now-async `openContainerExecWebSocket` rejects, dispose `term`/`fit` in a `catch` before returning. Keep the existing cleanup at `:55-62` (add `execWs?.dispose()` for the async case). This closes the leak path where a missing ref or failed socket leaves the xterm/FitAddon alive.

Theme: in `frontend/src/hooks/useTheme.ts` use `THEME_COLORS` from a shared constant and update the meta tag:
```ts
const THEME_COLORS: Record<Theme, string> = { dark: '#120e1e', light: '#f4f1f8' }
useEffect(() => {
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme])
  try {
    window.localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // L9: private-mode/quota failures must not break theme switching; the read path is already guarded.
  }
}, [theme])
```
These two hex values are the only allowed exception (meta theme-color cannot consume a CSS variable); keep them in sync with `:root` and `[data-theme='light']` tokens in `index.css`. The pre-paint script in `index.html` already sets `data-theme`; add `document.querySelector('meta[name=theme-color]')?.setAttribute('content', theme === 'light' ? '#f4f1f8' : '#120e1e')` there too.

Home copy (`Home.tsx`): replace the Spanish strings with English: `hero__eyebrow` → `Deployment platform`, `hero__title` → `Hello, this is Vela`, `hero__subtitle` → `Orchestrate, build and manage containers from one place.`; change `formatApiError(error, 'es')` → `formatApiError(error)`.

Dedup Images/Builder: extract the shared layout, message banner and loading skeleton into `SourceWorkspacePage.tsx` (props: `title`, `children`, `message`, `loading`) with styles in `source-page.css`; have `ImagesPage.tsx` and `BuilderPage.tsx` render through it, keeping their distinct forms intact. Do not change any API calls.

Consolidate the Containers poll loops to one source of truth (M6): move the deploy-job discovery interval from `ContainersPage.tsx:88-95` into `useActiveDeployJobs` (`frontend/src/hooks/useActiveDeployJobs.ts`) so there is exactly one interval; `ContainersPage` consumes the hook's `refresh` and in-flight state. Remove the duplicate `setInterval` from the page. This task solely owns `ContainersPage.tsx` — Task 10 no longer edits it.

While in `ContainersPage.tsx`, fix the render-phase ref assignment (L7, `:126`): replace `refreshRef.current = refresh` with a `useEffect(() => { refreshRef.current = refresh }, [refresh])`. This is the polling source-of-truth task, so the ref callback and the single interval are updated together and reviewed once.

Deep-link the tab / time-range state (M15), matching how Logs/Audit already use `useSearchParams`:
- `frontend/src/pages/AdminPage.tsx`: replace `useState<AdminTab>('users')` at `:12` with `const [searchParams, setSearchParams] = useSearchParams()` plus `const activeTab: AdminTab = searchParams.get('tab') === 'audit' && canViewAudit ? 'audit' : 'users'`. Add `selectTab(tab)` that copies `searchParams`, deletes `tab` for `users` (or sets `tab=audit`) and calls `setSearchParams(next, { replace: true })`. Point Task 11's `setActiveTab(next)` in `onTabKeyDown` and both tab buttons' click handlers at `selectTab` so keyboard and URL stay in sync.
- `frontend/src/pages/ResourceDashboardPage.tsx`: replace `useState<TimeRange>('24h')` at `:25` with `const [searchParams, setSearchParams] = useSearchParams()` and `const timeRange: TimeRange` derived from `searchParams.get('range')`, falling back to `'24h'` for anything outside `['1h','6h','24h','7d']`. In the `:84-93` button `onClick`, set `range` in a copied `URLSearchParams` via `setSearchParams(next, { replace: true })` (Task 11 adds `aria-pressed` to these same buttons; keep it).

Dead code: delete `frontend/src/pages/PlaceholderPage.tsx` (no references in `App.tsx`). Remove unused exports in `frontend/src/api/client.ts` only after `npm run typecheck` confirms they have no importers (use `grep` to verify each symbol before deleting).

JSDoc noise (L17): delete the redundant blocks that restate their function signature at `frontend/src/pages/BuilderPage.tsx:7-15`, `frontend/src/api/client.ts:279-286,299-305,328-335`, the helper JSDoc in `frontend/src/pages/containers/BuildConfigModal.tsx`, and `frontend/e2e/api-helpers.ts:9-18,42-46,84-89,122-127,135-141`. Keep one short comment only where it explains a non-obvious workaround (the `syntheticResponse` rationale at `api-helpers.ts:70-82`). No behavior changes.

- [ ] **Step 4: Run test to verify it passes** — `cd frontend; npm run test:e2e -- e2e/structure.spec.ts`. Expected: `2 passed`. Then full frontend gate.

- [ ] **Step 5: Commit** — `git add -A frontend && git commit -m "refactor(frontend): single poll source, WS tickets, shared source page, theme meta, English copy"`

---

### Task 13: CLI correctness, TUI and command tests (A1.1–A1.7, TUI, A.4)

**Files:**
- Create: `cli/src/commands/deploy.test.ts`, `cli/src/tui/app.test.tsx`, `backend/tests/test_runtime_config.py`
- Modify: `cli/src/commands/exec.ts:43-110`, `cli/src/commands/deploy.ts:22-56,58-120`, `cli/src/resolve.ts:31-43`, `cli/src/config.ts:55-67`, `cli/src/format.ts:1-11`, `cli/src/tui/app.tsx`, `cli/src/ws.ts`, `backend/app/api/routes/containers.py`, `backend/app/api/routes/settings.py`
- Test: `cli/src/commands/deploy.test.ts`, `cli/src/config.test.ts`, `backend/tests/test_runtime_config.py`

**Interfaces:**
- Consumes: `resolveContainerFromApi` (`resolve.ts`), `request` (`client.ts`), `waitForJob` (`deploy.ts`), `websocketUrl` (`ws.ts`); the new `GET /api/runtime-config` → `{ exec_max_session_seconds: int }`.
- Produces: `parseEnv(values)` exported from `deploy.ts`; `waitForJob(config, jobId, options?: { maxAttempts?: number; poll?: ... })`; `run()` understands `--no-wait`; `resolveContainerFromApi` uses exact-name lookup before listing; `formatTable` bounds column widths to 48; public `GET /api/runtime-config` exposes the server's `VELA_EXEC_MAX_SESSION_SECONDS`.

- [ ] **Step 1: Write the failing test** — `cli/src/commands/deploy.test.ts`:
```ts
import { describe, expect, test } from 'bun:test'

import { parseEnv, waitForJob } from './deploy'

describe('parseEnv', () => {
  test('splits on the first equals sign and rejects malformed values', () => {
    expect(parseEnv(['A=B=C', 'EMPTY='])).toEqual({ A: 'B=C', EMPTY: '' })
    expect(() => parseEnv(['NO_EQUALS'])).toThrow()
    expect(() => parseEnv(['=VALUE'])).toThrow()
  })
})

describe('waitForJob', () => {
  test('returns a succeeded job', async () => {
    const job = { job_id: 'j1', status: 'succeeded', phase: 'done' }
    const config = { server: 'http://127.0.0.1:1', token: 't' }
    const originalRequest = await import('../client')
    // deterministic: one poll then terminal state; exercise bounded-polling option
    const result = await waitForJob(config, 'j1', { maxAttempts: 1, poll: async () => [job] as never })
    expect(result).toEqual(job)
    void originalRequest
  })

  test('gives up after the bounded number of polls', async () => {
    const pending = { job_id: 'j1', status: 'in_progress', phase: 'queued' }
    await expect(
      waitForJob(
        { server: 'http://127.0.0.1:1', token: 't' },
        'j1',
        { maxAttempts: 2, poll: async () => [pending] as never },
      ),
    ).rejects.toThrow(/timed out|did not complete/i)
  })
})
```
Add to `cli/src/config.test.ts`:
```ts
test('server is resolved from env/stored config, not a dead flag', () => {
  expect(resolveConfig({}, { VELA_API_URL: 'http://example.test/' })).toMatchObject({
    server: 'http://example.test',
  })
})
```
Add `backend/tests/test_runtime_config.py` so the CLI's timeout source is a real API contract:
```python
from fastapi.testclient import TestClient


def test_runtime_config_exposes_exec_session_cap(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/runtime-config")
    assert response.status_code == 200
    assert response.json()["exec_max_session_seconds"] >= 1
```

- [ ] **Step 2: Run test to verify it fails** — `cd cli; bun test` (`parseEnv` not exported; `waitForJob` ignores options) and `cd backend; python -m pytest tests/test_runtime_config.py -q` (404 on `/api/runtime-config`).

- [ ] **Step 3: Write minimal implementation** — `cli/src/commands/deploy.ts`: export `parseEnv` (`export function parseEnv(...)`) and add bounded polling:
```ts
interface WaitOptions {
  maxAttempts?: number
  poll?: (config: { server: string; token: string }) => Promise<DeployJob[]>
}

export async function waitForJob(
  config: { server: string; token: string },
  jobId: string,
  options: WaitOptions = {},
): Promise<DeployJob> {
  const maxAttempts = options.maxAttempts ?? 600
  const poll = options.poll ?? ((cfg) => request<DeployJob[]>(cfg, 'GET', '/deploys/active'))
  let lastPhase = ''
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const jobs = await poll(config)
    const job = jobs.find((candidate) => candidate.job_id === jobId)
    if (!job) throw new VelaError(1, 'Deploy job disappeared before completing.')
    if (job.phase !== lastPhase) {
      console.log(`[${job.phase}]${job.phase_detail ? ` ${job.phase_detail}` : ''}`)
      lastPhase = job.phase
    }
    if (job.status === 'succeeded') return job
    if (job.status === 'failed') throw new VelaError(1, job.error?.detail ?? 'Deploy failed.')
    await Bun.sleep(1000)
  }
  throw new VelaError(1, 'Deploy job did not complete in time.')
}
```
Add `--no-wait` to the `run` options (`"no-wait": { type: "boolean" }`) and after the accepted response:
```ts
  if (values['no-wait']) {
    console.log(accepted.job_id)
    return 0
  }
```
Stop hard-coding `git_branch: 'main'`: when `values.branch` is absent, delete the key (`delete body.git_branch`) and let the server default to `main` (`builder.py:63`). Do not call `analyze-source` from the deploy command — the server already infers the branch for deploys, so that would add a second source of truth.

`cli/src/commands/exec.ts`: replace any hard-coded 10-minute timer with the server value from the new public `GET /api/runtime-config` (there is no `exec_max_session_seconds` field on any existing `/api/settings` response — verified in `backend/app/api/routes/settings.py` and `backend/app/api/schemas.py`, so reading `/settings` would silently hard-code the fallback). Add the endpoint in `backend/app/api/routes/settings.py`:
```python
@router.get("/runtime-config")
async def runtime_config() -> dict[str, int]:
    from app.api.routes.containers import _exec_max_session_seconds

    return {"exec_max_session_seconds": _exec_max_session_seconds()}
```
(the import is lazy to avoid a module-level cycle; `_exec_max_session_seconds` at `containers.py:178` reads `VELA_EXEC_MAX_SESSION_SECONDS` with the 3600 default). Then in the CLI:
```ts
  const execMaxSeconds = await request<{ exec_max_session_seconds: number }>(
    config, 'GET', '/runtime-config'
  ).then((s) => s.exec_max_session_seconds).catch(() => 3600)
  const timeout = setTimeout(() => { try { socket.close() } catch { /* already closed */ } }, execMaxSeconds * 1000)
```
Call `clearTimeout(timeout)` in `restore()`. Use that setting for the client-side cap in `ws.ts` log streaming too.

**WS-ticket migration (required — Task 7 removed `access_token` query auth).** In `cli/src/ws.ts`, change `websocketUrl(server, path, token, params)` to `websocketUrl(server, path, ticket, params)` and replace `url.searchParams.set("access_token", token)` with `url.searchParams.set("ticket", ticket)`. Add an exported helper using the existing `request` client:
```ts
export async function mintWsTicket(
  config: { server: string; token: string },
  containerId: string,
  purpose: "logs" | "exec",
): Promise<string> {
  const { ticket } = await request<{ ticket: string }>(
    config, 'POST', `/containers/${containerId}/ws-ticket?purpose=${purpose}`
  )
  return ticket
}
```
In `streamLogs`, call `mintWsTicket(config, containerId, "logs")` before building the URL and pass that value to `websocketUrl`. In `cli/src/commands/exec.ts`, do the same with purpose `"exec"`. The ticket is 60-second, single-use, and bound to container + purpose (contract in `.superpowers/sdd/2026-11-20-defect-remediation/task-7-report.md` §"Cross-task WS-ticket interface"). Add a focused CLI test (with an injected fetch) asserting the ticket is minted and appears as `ticket=` in the WS URL and that `access_token` is absent. Without this, `vela logs -f` and `vela exec` are broken after Task 7.

`cli/src/resolve.ts`: in `resolveContainerFromApi`, do an exact-name lookup before the paginated list:
```ts
  const exact = await request<ContainerInfo | null>(config, 'GET', `/containers/by-name/${encodeURIComponent(query)}`).catch(() => null)
  if (exact) return exact
  // existing paginated-list resolution follows
```
Add the `GET /api/containers/by-name/{name}` route in `backend/app/api/routes/containers.py` (thin handler using `require_container_access` with `action="read"` after the name lookup), so the CLI path exists. Keep `VelaError(4, ...)` for not-found — **merge note:** `35f0db9` changes this to 404; resolve in favor of the CLI's documented exit code 4.

`cli/src/config.ts`: remove the dead `server` flag path — change `resolveConfig(flags: { token?: string }, ...)` and drop `flags.server` from line 60 (`env.VELA_API_URL ?? stored?.server ?? DEFAULT_SERVER`). `main.ts` already publishes `--server` via `process.env.VELA_API_URL`, so user behavior is unchanged.

`cli/src/format.ts`: bound column widths:
```ts
  const widths = headers.map((header, index) =>
    Math.min(48, Math.max(header.length, ...rows.map((row) => (row[index] ?? '').length))),
  )
```
`cli/src/tui/app.tsx`: make `l` (logs) and `e` (exec) call the same command handlers as the CLI (or remove the keybindings); ensure the `deploying` flag is cleared in a `finally` block. Add a TUI test in `cli/src/tui/app.test.tsx` for the chosen behavior.

- [ ] **Step 4: Run test to verify it passes** — `cd cli; bun test; bunx tsc --noEmit; bun build --compile src/main.ts --outfile dist/vela`. Expected: all CLI tests pass and the binary compiles. Then `cd backend; python -m pytest tests/test_runtime_config.py -q` plus the full backend gate (two new routes: `/api/runtime-config` and `/api/containers/by-name/{name}`), and the full frontend gate unchanged.

- [ ] **Step 5: Commit** — `git add -A cli && git add backend/app/api/routes/containers.py backend/app/api/routes/settings.py backend/tests/test_runtime_config.py && git commit -m "fix(cli): bounded job polling, no-wait, runtime-config exec timeout, name lookup, table widths"`

---

### Task 14: Infra defaults, volume bind, edge/TLS and compose hardening (B1.1, B1.3, B1.4, B2, B3)

**Files:**
- Create: `backend/tests/test_bootstrap_secrets.py`
- Modify: `backend/app/api/app.py:142-156`, `backend/app/bootstrap_env.py`, `.env.example`, `docker-compose.yml:50-144`, `frontend/nginx.conf:19-21`, `traefik/static/spa.yaml:1-26`, `docker-compose.dev.yml`
- Test: infra verification only (`docker compose config -q` + `up -d --build` + `ps` + `down`) + `backend/tests/test_bootstrap_secrets.py`

**Interfaces:**
- Consumes: `frontend/nginx.conf` client_max_body_size 105m vs `VOLUME_UPLOAD_MAX_BYTES = 100 MB`; `velaunq.ddns.net` occurrences in `app.py:149-150`, `.env.example`, `docker-compose.yml`, `frontend/vite.config.ts` and `traefik/static/spa.yaml:21`.
- Produces: neutral defaults, named `volume_uploads` volume, env-gated Traefik dashboard/staging resolver, fail-closed startup secret validation, hardening limits in compose.

- [ ] **Step 1: Write the failing test** — a repo-wide check is the test (no new test framework):
```powershell
cd <repo-root>
$bad = Select-String -Path backend/app/api/app.py,.env.example,docker-compose.yml,frontend/vite.config.ts,traefik/static/spa.yaml -Pattern 'velaunq\.ddns\.net' -ErrorAction SilentlyContinue
if ($bad) { throw "Host-specific default still present: $bad" }
$shellSyntax = Select-String -Path traefik/static/spa.yaml -Pattern '\$\{' -ErrorAction SilentlyContinue
if ($shellSyntax) { throw 'Traefik dynamic config must use Go templates, not Compose interpolation: ' + $shellSyntax }
```
Expected: fails immediately, listing every `velaunq.ddns.net` occurrence (and the `${...}` in `spa.yaml` once the host is replaced).

- [ ] **Step 2: Run test to verify it fails** — run the PowerShell snippet above. Expected: throw with the file list.

- [ ] **Step 3: Write minimal implementation** — replace every `velaunq.ddns.net` with a neutral placeholder: `app.example.com` in CORS (`app.py:149-150`), `.env.example`, compose and Vite config; in `traefik/static/spa.yaml` replace `main: velaunq.ddns.net` with `main: '{{ env "VELA_PUBLIC_HOST" }}'` and document `VELA_PUBLIC_HOST`.

**Traefik syntax (H-3):** `traefik/static/spa.yaml` is a **dynamic** file-provider config, not a Compose file. `${VELA_PUBLIC_HOST:-app.example.com}` / `${VELA_TRAEFIK_ACME_RESOLVER:-letsencrypt}` are Compose/CLI interpolation and would be treated as literal host/resolver names or rejected. Use Traefik's Go templates everywhere in that file:
```yaml
      tls:
        certResolver: '{{ env "VELA_TRAEFIK_ACME_RESOLVER" }}'
        domains:
          - main: '{{ env "VELA_PUBLIC_HOST" }}'
```
Supply the defaults as real container env vars on the `traefik` service in `docker-compose.yml` (where `${VAR:-default}` interpolation *is* correct):
```yaml
    environment:
      VELA_PUBLIC_HOST: ${VELA_PUBLIC_HOST:-app.example.com}
      VELA_TRAEFIK_ACME_RESOLVER: ${VELA_TRAEFIK_ACME_RESOLVER:-letsencrypt}
```
`docker compose -f docker-compose.yml config -q` plus `docker compose ps` in Step 4 must show Traefik healthy with the rendered route/resolver — this is the check that the templates resolve.

In `backend/app/bootstrap_env.py` add fail-closed validation before the app is built:
```python
def require_deployment_secrets() -> None:
    """Fail closed when required secrets are blank; no insecure defaults."""
    import os

    missing = [
        name for name in ("VELA_AUTH_SECRET", "VELA_TOKEN_ENCRYPTION_KEY")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise RuntimeError(
            "Missing required secrets: " + ", ".join(missing) +
            ". Set them in .env (see .env.example)."
        )
```
Call it from `backend/app/api/app.py` at the top of `create_app()` (after `import app.bootstrap_env`) **only when** `VELA_E2E` is not `1`, so tests/E2E keep their injected secrets. Add one unit test in `backend/tests/test_bootstrap_secrets.py` asserting `RuntimeError` when both are blank under `monkeypatch`.

In `docker-compose.yml`:
- Replace the host bind at lines 76-80 with a named volume `volume_uploads:/data/volume-uploads` and add `volume_uploads:` under `volumes:`. Set `VELA_VOLUME_UPLOADS_HOST_DIR` empty by default and document in `.env.example` that a pre-created host dir (owned by the API user) is the alternative — this prevents a fresh Linux host from creating a root-owned bind.
- Add an HTTP→HTTPS redirect router in `traefik/static/spa.yaml`:
```yaml
    vela-redirect:
      rule: 'Host(`{{ env "VELA_PUBLIC_HOST" }}`)'
      service: vela-spa-svc
      entryPoints: [web]
      middlewares: [vela-https-redirect]
  middlewares:
    vela-https-redirect:
      redirectScheme:
        scheme: https
        permanent: true
```
- Gate the insecure dashboard: replace `--api.insecure=true` with `--api.dashboard=${VELA_TRAEFIK_DASHBOARD:-false}` and bind `127.0.0.1:8080:8080` only when enabled (document `VELA_TRAEFIK_DASHBOARD=1` for dev).
- Add a staging ACME option: `--certificatesresolvers.staging.acme.caserver=https://acme-staging-v02.api.letsencrypt.org/directory` plus storage/httpchallenge flags, and switch `spa.yaml` `certResolver` to the Go template `'{{ env "VELA_TRAEFIK_ACME_RESOLVER" }}'` (default supplied by the `traefik` service env above).
- Add resource limits/hardening to `postgres`, `api`, `web`, `traefik` (e.g. `deploy.resources.limits.cpus/memory`, `security_opt: [no-new-privileges:true]`, `read_only: true` where possible with tmpfs, `cap_drop: [ALL]` for `web`/`traefik`). Keep the existing healthchecks and `depends_on` conditions intact.
- Align nginx `client_max_body_size 105m` with `VELA_VOLUME_UPLOAD_MAX_BYTES` **for any configured value** (not just the 100 MB default). A static 105m with a comment still lets nginx return 413 before the app when the app limit is raised. Render the config at container start from the already-committed `frontend/nginx.conf` (no new template file): mount it read-only at `/etc/nginx/nginx-source.conf`, put a tmpfs on `/etc/nginx/conf.d` (writable by the unprivileged nginx user, uid 101), and override the `web` entrypoint:
```yaml
  web:
    environment:
      VELA_VOLUME_UPLOAD_MAX_BYTES: ${VELA_VOLUME_UPLOAD_MAX_BYTES:-104857600}
    volumes:
      - ./frontend/nginx.conf:/etc/nginx/nginx-source.conf:ro
    tmpfs:
      - /etc/nginx/conf.d:uid=101,gid=101,mode=0755
    entrypoint:
      - /bin/sh
      - -c
      - |
        max_mb=$$(( $${VELA_VOLUME_UPLOAD_MAX_BYTES:-104857600} / 1048576 + 5 ))
        sed "s/client_max_body_size 105m;/client_max_body_size $${max_mb}m;/" \
          /etc/nginx/nginx-source.conf > /etc/nginx/conf.d/default.conf
        exec nginx -g 'daemon off;'
```
  The `+5` gives nginx headroom over the app's authoritative limit so the app's 413 (with its client-facing message) wins. `$$` escapes Compose interpolation so the shell expands the variables at runtime. The infra gate in Step 4 confirms the rendered config is accepted and `/api` still proxies correctly.
- Document in `.env.example`: `VELA_PUBLIC_HOST`, `VELA_TRAEFIK_ACME_RESOLVER`, `VELA_TRAEFIK_DASHBOARD`, `VELA_GIT_ALLOW_PRIVATE_ENDPOINTS` (Task 8), `VELA_API_CONTAINER_USER` (with its compose meaning), and the two previously undocumented backend vars `VELA_LLM_ALLOW_PRIVATE_ENDPOINTS` (default for `ALLOW_PRIVATE_ENV` in `core/security/outbound_url.py:11`) and `VELA_LLM_CACHE_DIR` (cache location in `core/llm/cache.py:16`). If `.env.example` already has a `VELA_GEMINI_MODEL` row, keep exactly one row and set it to `gemini-3.1-flash-lite` (Task 16's gate enforces this).

- [ ] **Step 4: Run test to verify it passes** — run the PowerShell grep snippet (expect no output), then the full infra gate:
```powershell
docker compose -f docker-compose.yml config -q
docker compose up -d --build
docker compose ps    # confirm migrate exited 0 and api is healthy
docker compose down
```
Then backend gate (fail-closed test) and frontend build (Vite config changed).

**Merge note:** `aad7943` on `fix/security-and-cli-hardening` already fixed the Linux volume-upload bind; resolving the merge later should keep one equivalent fix (named volume) and drop the duplicate.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "fix(infra): neutral defaults, named upload volume, TLS/dashboard gating, compose hardening"`

---

### Task 15: CI paths and jobs (B1.2, B4)

**Files:**
- Modify: `.github/workflows/ci.yml:1-108`
- Test: workflow YAML validation via `docker compose` not applicable — use local shell check on YAML parse plus the full suite.

**Interfaces:**
- Consumes: existing jobs `backend-tests`, `cli-tests`, `e2e`; Node CI currently `"22"` (`:84`) while the production image is `node:20-alpine` (`frontend/Dockerfile:1`); Bun `latest`; no lint/mypy/build jobs.
- Produces: infra paths in both `paths:` filters; `node-version: "20"` in **both** the existing `e2e` job and the new lint job (matching `frontend/Dockerfile:1`); `bun-version: "1.4.4"`; `lint-and-typecheck` job; `infra-smoke` job.

- [ ] **Step 1: Write the failing test** — `ci-check.ps1` run from repo root (inline in the step, not committed):
```powershell
$ci = Get-Content .github/workflows/ci.yml -Raw
foreach ($needle in 'ruff check .','mypy app/ tests/','npm run lint','npm run typecheck','npm run build','docker compose -f docker-compose.yml config -q','docker-compose.yml','traefik/**','frontend/nginx.conf','bun-version: "1.4.4"','node-version: "20"') {
  if (-not $ci.Contains($needle)) { throw "CI is missing: $needle" }
}
if ($ci.Contains('node-version: "22"')) { throw 'CI Node pin still disagrees with frontend/Dockerfile:1 (node:20-alpine)' }
if (([regex]::Matches($ci, 'node-version: "20"')).Count -lt 2) { throw 'Both the e2e and lint-and-typecheck jobs must pin Node 20' }
```
Expected: throws on the first missing needle (`ruff check .`).

- [ ] **Step 2: Run test to verify it fails** — run the snippet. Expected: throw.

- [ ] **Step 3: Write minimal implementation** — in `.github/workflows/ci.yml`, add to both `paths:` lists:
```yaml
      - "docker-compose.yml"
      - "docker-compose.dev.yml"
      - "traefik/**"
      - "frontend/nginx.conf"
      - ".env.example"
```
Pin Bun: replace `bun-version: latest` with `bun-version: "1.4.4"`. Pin Node to the production image: `frontend/Dockerfile:1` is `FROM node:20-alpine`, so change the existing `e2e` job's `node-version: "22"` (`:84`) to `node-version: "20"` and add `# keep in sync with frontend/Dockerfile:1 (node:20-alpine)`. Use the same `"20"` in the new `lint-and-typecheck` job below — do not leave a conditional or leave either job on 22.
Add a `lint-and-typecheck` job:
```yaml
  lint-and-typecheck:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip, cache-dependency-path: backend/pyproject.toml }
      - run: pip install -e "backend/[dev]"
      - name: Backend lint
        working-directory: backend
        run: ruff check .
      - name: Backend typecheck
        working-directory: backend
        run: mypy app/ tests/
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: npm, cache-dependency-path: frontend/package-lock.json } # keep in sync with frontend/Dockerfile:1
      - run: npm ci
        working-directory: frontend
      - name: Frontend lint
        working-directory: frontend
        run: npm run lint
      - name: Frontend typecheck
        working-directory: frontend
        run: npm run typecheck
      - name: Frontend build
        working-directory: frontend
        run: npm run build
```
Add an `infra-smoke` job:
```yaml
  infra-smoke:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - name: Validate compose file
        run: docker compose -f docker-compose.yml config -q
      - name: Build and start stack
        run: docker compose up -d --build
      - name: Wait for API health
        run: |
          for i in $(seq 1 30); do
            if curl -fsS http://127.0.0.1:8081/api/health >/dev/null; then exit 0; fi
            sleep 5
          done
          docker compose ps
          exit 1
      - name: Tear down
        if: always()
        run: docker compose down -v
```
Keep the existing pytest, CLI and Playwright jobs unchanged.

- [ ] **Step 4: Run test to verify it passes** — rerun the PowerShell snippet (expect no throw), then `cd backend; python -m pytest tests -q; ruff check .; mypy app/ tests/`, `cd frontend; npm run build; npm run lint; npm run typecheck`, and `docker compose -f docker-compose.yml config -q`.

- [ ] **Step 5: Commit** — `git add .github/workflows/ci.yml && git commit -m "ci: cover infra paths and add lint/typecheck/build + compose smoke jobs"`

---

### Task 16: Documentation drift + final verification and deslop

**Files:**
- Modify: `README.md`, `.env.example`, `docs/specs/2026-11-20-defect-remediation-design.md` (status line only)
- Test: full verification gate

**Interfaces:**
- Consumes: all prior tasks' final state; `DEFAULT_LLM_MODEL = "gemini-3.1-flash-lite"` (Task 9); E2E behaviour (live API + Vite, no `page.route`).
- Produces: concise, accurate README; all spec units mapped in `Self-review`; clean diff.

- [ ] **Step 1: Write the failing test** — documentation assertions in one PowerShell snippet:
```powershell
$readme = Get-Content README.md -Raw
$envExample = Get-Content .env.example -Raw
$provider = Get-Content backend/app/core/llm/provider.py -Raw
if ($readme.Contains('page.route')) { throw 'README still claims page.route mocking' }
# Exactly one effective Gemini default across README, .env.example and code.
foreach ($file in @($readme, $envExample, $provider)) {
  if ($file -match 'gemini-2\.0-flash|gemini-3\.5-flash-lite') { throw 'A conflicting Gemini default survives' }
}
$envModelRows = [regex]::Matches($envExample, '(?m)^VELA_GEMINI_MODEL=(.+)$')
if ($envModelRows.Count -ne 1) { throw ".env.example must contain exactly one VELA_GEMINI_MODEL row, found $($envModelRows.Count)" }
if ($envModelRows[0].Groups[1].Value -ne 'gemini-3.1-flash-lite') { throw ".env.example VELA_GEMINI_MODEL must be gemini-3.1-flash-lite, got '$($envModelRows[0].Groups[1].Value)'" }
$codeDefaults = [regex]::Matches($provider, 'DEFAULT_LLM_MODEL\s*=\s*"([^"]+)"')
if ($codeDefaults.Count -ne 1 -or $codeDefaults[0].Groups[1].Value -ne 'gemini-3.1-flash-lite') { throw 'provider.py must define exactly one DEFAULT_LLM_MODEL (gemini-3.1-flash-lite)' }
foreach ($needle in 'VELA_GIT_ALLOW_PRIVATE_ENDPOINTS','VELA_API_CONTAINER_USER','VELA_PUBLIC_HOST','VELA_LLM_ALLOW_PRIVATE_ENDPOINTS','VELA_LLM_CACHE_DIR','instructor') {
  if (-not $readme.Contains($needle) -and -not $envExample.Contains($needle)) {
    throw "Missing documented item: $needle"
  }
}
```
Expected: throws on `page.route` (and would also catch the stale `gemini-2.0-flash` and missing LLM vars).

- [ ] **Step 2: Run test to verify it fails** — run the snippet. Expected: throw.

- [ ] **Step 3: Write minimal implementation** — in `README.md`:
  - Replace the E2E paragraph at lines 261-270 with: the suite drives the real SPA against a real FastAPI process on ports 8000/5173, seeded users come from `frontend/e2e/constants.ts` (kept in sync with `backend/app/e2e_support.py`), no `page.route` mocking for app flows (only external OAuth redirects may be intercepted). Keep the command table.
  - Ownership model: replace the line at 154 with "Most `/api/containers/**` routes require a bearer token; access is scoped by project membership and the Docker labels `vela.owner_id` / `vela.project_id`. Instructors may manage members and invitations across projects; every mutation is audit-logged."
  - Clerk endpoints: document `GET /api/auth/config`, `POST /api/auth/clerk/exchange`, and that `VELA_ALLOWED_ORIGINS` must list the SPA origin (fail-closed).
  - Traefik file name: state the dynamic file is `traefik-http.yml` (compose) or the absolute path in `VELA_TRAEFIK_DYNAMIC_FILE`; remove stale `resources/traefik-http.json` instructions where they conflict.
  - Gemini defaults: after Task 9 there is exactly one effective default in code (`gemini-3.1-flash-lite`). Keep both README env-var rows quoting that value. **In `.env.example:135` change `VELA_GEMINI_MODEL=gemini-2.0-flash` to `VELA_GEMINI_MODEL=gemini-3.1-flash-lite`** and ensure there is only one `VELA_GEMINI_MODEL` row — Task 16's gate checks this file directly, not just README.
  - Cross-check the env docs added in Task 14: `.env.example` must contain `VELA_GIT_ALLOW_PRIVATE_ENDPOINTS`, `VELA_API_CONTAINER_USER`, `VELA_PUBLIC_HOST`, `VELA_LLM_ALLOW_PRIVATE_ENDPOINTS` and `VELA_LLM_CACHE_DIR`. Keep the README concise — no new long sections.
  - In the spec file change the status line to `Status: Approved 2026-11-20; implemented via docs/plans/2026-11-20-defect-remediation.md.`

- [ ] **Step 4: Run test to verify it passes** — rerun the PowerShell snippet (expect no throw), then the **full verification gate**:
```powershell
cd backend
$env:VELA_FAKE_ORCHESTRATOR="1"; $env:VELA_DATABASE_URL="sqlite+aiosqlite:///:memory:"
python -m pytest tests -q
ruff check .
mypy app/ tests/
cd ../frontend
npm run build
npm run lint
npm run typecheck
npm run test:e2e
cd ..
docker compose -f docker-compose.yml config -q
docker compose up -d --build
docker compose ps
docker compose down
```
Deslop the cumulative branch diff: remove unnecessary comments, abnormal `try`/`except` on trusted paths, type-silencing `any` casts, and structure diverging from surrounding code — without changing behavior except for clear bugs. Re-run the backend and frontend gates after deslopping.

- [ ] **Step 5: Commit** — `git add README.md .env.example docs/specs/2026-11-20-defect-remediation-design.md && git commit -m "docs: correct E2E, ownership, Clerk, Traefik and model default drift"`

---

## Self-review

| Spec unit | Task | Notes |
|---|---|---|
| 1 — Router auth, admin gates, route auth test, audit (F1–F3, F27) | 1 | Covers all; OAuth `github/start` and `callback` treated as public. Files list includes both new test files; Step 4 expects the exact count (`2 passed`). |
| 2 — Traefik backtick guard (F4) | 2 | Exact `_path_rule` root fix. |
| 3 — Stack delete auth ordering (F5) | 3 | Shared `require_stack_write_access` used by both delete paths; test asserts Docker state. |
| 4 — Replica runtime config (F6) | 4 | Migration 0023 adds `DeploymentRecord.deploy_config`; `_evaluate_policy` resolves the policy name to the live container's **Docker id** via `_base_container_info` before calling `load_deploy_config_snapshot`, and the test asserts a name-based lookup misses. |
| 5 — Upload reads, quotas, containment (F7, F22, F23) | 5 | Streamed reads, per-user lock, `is_relative_to`. |
| 6 — PAT lifecycle + migration (F11) | 6 | Migration 0024; existing rows non-expiring so CLI keeps working. |
| 7 — Auth hardening (F8, F12, F13, F15, M7) | 7 | Throttle, Clerk fail-closed, iss/aud, single-use ticket. conftest autouse reset prevents the limiter from 429-ing the ~10 existing token-creation tests. WS-ticket test seeds the container via `fake_orchestrator.seed_container` and asserts anonymous 401 + authenticated 200. Log-stream timeout stays in Task 9 per unit table. |
| 8 — Git SSRF + docs (F10) | 8 | `validate_git_remote` reuses the outbound guard; full `validate_outbound_url` body shown (no placeholder); new opt-in env var. |
| 9 — Backend cleanup (F9, F18, F19, F20, F21, F26) | 9 | F9/F18/F26 concrete; F19/F20/F21 mapped to the duplicate `DEFAULT_LLM_MODEL`, log-stream timeout and instructor-audit cleanup. The three evidence reports are present in `.subagent-reports/` and were read; no best-effort downgrade. |
| 10 — Frontend correctness (H1, M1, M13, L2, L6–L9, L14) | 10 | H1/M1/M13/L6/L14 concrete. Folded in from elsewhere: **H2** (pin Clerk script), **L3** (remove injected script on unmount) and **L10** (all timestamp locales). L7/L8/L9 are implemented in Task 12 (same `ContainersPage`/terminal/theme files as its poll and WS work); this task no longer touches `ContainersPage`. |
| 11 — Frontend a11y/UX (H3, M2–M5, M11, M12, L1, L4, L5, L11, L12) | 11 | Skip link, labelled main, links, arrow-key tabs + `aria-labelledby`, ConfirmDialog stack/template deletion, unsaved guard, live-region banner, submit-on-Enter, input names, `aria-pressed`, shared `Skeleton` loading states, duplicate-label and busy-copy fixes — all with explicit file/line steps. `DockerfileTemplatesSection` path corrected to `frontend/src/components/`. |
| 12 — Frontend structure (M6–M10, M14, M15, L3, L10, L15–L17) | 12 | Poll consolidation + render-phase ref fix (L7), WS ticket callers + terminal cleanup (L8), theme localStorage guard (L9), URL-synced Admin tab/time-range (M15), dedup, theme meta, copy, dead code, JSDoc removal. L3/L10 folded into Task 10; WS-ticket E2E test seeds a running container via `deployImageContainer`. |
| 13 — CLI correctness/TUI/tests (A1.1–A1.7, TUI, A.4) | 13 | Bounded polling, `--no-wait`, exec timeout sourced from a real new `GET /api/runtime-config` (no speculative `/api/settings` field), deterministic branch handling, exact-name lookup, table widths, TUI keys; Files list includes all edited/created files. |
| 14 — Infra defaults/bind/edge/TLS/compose (B1.1, B1.3, B1.4, B2, B3) | 14 | Neutral defaults, named upload volume, fail-closed secrets, Go-template Traefik dynamic config (`{{ env "VAR" }}`, defaults supplied as Compose env), runtime-rendered nginx body limit, compose hardening, all env vars documented. B3 feature parts explicitly excluded per spec. |
| 15 — CI paths/jobs (B1.2, B4) | 15 | Paths, lint/typecheck/build, compose smoke; Node pinned to `20` in **both** the e2e and lint jobs to match `frontend/Dockerfile:1`; Bun pinned to `1.4.4`; existing jobs kept. |
| 16 — Documentation drift | 16 | README/env/spec corrections; gate checks `.env.example` and `provider.py` directly so exactly one Gemini default (`gemini-3.1-flash-lite`) survives; full gate + deslop. |

**Requirements with no dedicated task:** none from the spec's decision sections; every spec unit maps to one of the 16 tasks, and header-only claims were either given concrete steps or explicitly folded into a neighbouring task with steps (noted above).

**Audit finding disposition:** all 27 findings in `.subagent-reports/plan-audit.md` (H-1…H-5, M-1…M-13, L-1…L-9) were re-verified against the cited source files and accepted — fixed or folded inline; **none rejected**. Clarification with evidence (not a rejection): the render-phase assignment called out under M-6/L7 originates at `frontend/src/pages/ContainersPage.tsx:126` (`refreshRef.current = refresh`), not from Task 10's use of `refreshRef.current()` in success handlers; the underlying conflict (two tasks editing `ContainersPage`) is real, so all `ContainersPage` edits now live only in Task 12.

**Caveats:** (1) several fixes (login throttle, Git scheme validation, CLI exec timeout, Linux volume bind) overlap commits that exist only on `fix/security-and-cli-hardening` and will need explicit merge-conflict resolution — each affected task carries a merge note; (2) the spec names only three such commits, but the branch actually contains five relevant ones (`35f0db9`, `c03fcbd`, `f1517bb`, `aad7943`, `834cceb`). The Clerk pin value (`5.97.0`) is a concrete planned version; the implementer must confirm the exact release resolves and bump the single constant explicitly if needed.
