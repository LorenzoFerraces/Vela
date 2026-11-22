# Group B — Externalized state & routing (F04, F17) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the broken Kubernetes router option and make deploy jobs, traffic state, WebSocket tickets and object storage externalized so the API can run multiple replicas behind Traefik without losing state.

**Architecture:** New ORM models for deploy jobs, traffic routes and WebSocket tickets, plus a migration from head `0024_api_token_lifecycle`. `DeployJobRegistry` keeps its `app.state.deploy_jobs` seam and its dataclass projection but becomes async, backed by the DB; all call sites (including the stack deploy callbacks) are converted to `await`. A `DatabaseTrafficRouter` implements the existing `TrafficRouter` ABC, persists `RouteSpec` JSON in Postgres, and regenerates the shared Traefik dynamic file; the legacy file router stays the single-node default and an importer migrates the old sidecar. Object storage defaults to R2 only in compose; `deps.py` keeps `memory` as the direct-run default so tests are unaffected. Multi-replica is an opt-in compose profile with a single scheduler replica for the background loops.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, boto3 (already pinned), Docker Compose profiles, pytest + `TestClient`.

## Global Constraints

- Worktree root: `C:\Users\lolo\.local\share\opencode\worktree\ab1b01\defect-remediation`. Paths are relative to it.
- Keep `GET /api/deploys/active` response shape byte-for-byte identical — `frontend/e2e/deploy-progress.spec.ts` depends on it.
- Keep every private helper in `traefik_file_traffic_router.py` (`_path_rule`, `_build_traefik_document`, `_atomic_write_bytes`) importable from that module.
- `TERMINAL_JOB_TTL = 300` remains the single source of truth for job retention.
- Alembic head is `0024_api_token_lifecycle`; new revisions are `0025_*` with `down_revision = "0024_api_token_lifecycle"`.
- Verification per task: `cd backend && python -m pytest tests -q` (with `VELA_FAKE_ORCHESTRATOR=1`, `VELA_DATABASE_URL=sqlite+aiosqlite:///:memory:`) and `ruff check . && mypy app/ tests/`. Compose changes additionally require `docker compose -f docker-compose.yml config -q`, then `up -d --build`, `ps`, `down` per `AGENTS.md`.
- The K8s **manifest parser** (`core/stacks/k8s_parser.py` etc.) stays — only the traffic router adapter is removed.

---

### Task 1: F17 — remove the Kubernetes traffic router option

**Files:**
- Delete: `backend/app/core/traffic/kubernetes_traffic_router.py`
- Modify: `backend/app/api/deps.py`, `backend/app/api/app.py`, `backend/app/core/__init__.py`, `backend/app/core/traffic/__init__.py`, `backend/app/core/traffic/traffic_router.py`, `README.md`, `.env.example`, `AGENTS.md`
- Test: `backend/tests/test_traffic_router_config.py`

**Interfaces:**
- Consumes: `TrafficRouterError`, `_traffic_router_from_env`.
- Produces: `validate_traffic_router_config() -> None` called eagerly from `create_app()`.

- [ ] **Step 1: Write a failing test** in `backend/tests/test_traffic_router_config.py`

```python
import pytest

from app.api.deps import validate_traffic_router_config
from app.core.exceptions import TrafficRouterError


def test_kubernetes_is_rejected_with_supported_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_TRAFFIC_ROUTER", "kubernetes")
    with pytest.raises(TrafficRouterError) as excinfo:
        validate_traffic_router_config()
    assert "noop" in str(excinfo.value)
    assert "traefik_file" in str(excinfo.value)
    assert "kubernetes" not in str(excinfo.value)


@pytest.mark.parametrize("mode", ["noop", "traefik_file"])
def test_supported_modes_are_accepted(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_TRAFFIC_ROUTER", mode)
    monkeypatch.setenv("VELA_TRAEFIK_DYNAMIC_FILE", "/tmp/traefik-http.yml")
    validate_traffic_router_config()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_traffic_router_config.py -q`
Expected: FAIL — `validate_traffic_router_config` not defined.

- [ ] **Step 3: Change `backend/app/api/deps.py`**

Delete the `KubernetesTrafficRouter` import at line 33, delete the `case "kubernetes": return KubernetesTrafficRouter()` branch, and change the fallback to:

```python
    raise TrafficRouterError(
        f"Unsupported VELA_TRAFFIC_ROUTER={mode!r}; use noop or traefik_file."
    )
```

Add the eager validator next to the factory:

```python
def validate_traffic_router_config() -> None:
    """Fail at startup for an unsupported router instead of failing on first request."""
    _traffic_router_from_env()
```

Update the `get_traffic_router()` docstring to list only the two supported modes.

- [ ] **Step 4: Call the validator in `create_app()`** in `backend/app/api/app.py` immediately after the `bootstrap_env.require_deployment_secrets()` block:

```python
    validate_traffic_router_config()
```

Add `validate_traffic_router_config` to the existing import from `app.api.deps`.

- [ ] **Step 5: Remove remaining references**

- `backend/app/core/__init__.py`: remove the `KubernetesTrafficRouter` import and its `__all__` entry.
- `backend/app/core/traffic/__init__.py`: remove the Kubernetes mention from the docstring.
- `backend/app/core/traffic/traffic_router.py`: change the ABC docstring to "(Traefik file provider, noop, etc.)".
- `README.md` line ~90: `| VELA_TRAFFIC_ROUTER | noop (default) or traefik_file |`.
- `.env.example` lines ~89-92: replace the three comment lines with two options, dropping "(scaffold)".
- `AGENTS.md` line 83: same table row update as README.

- [ ] **Step 6: Run tests**

Run: `cd backend && python -m pytest tests/test_traffic_router_config.py tests/test_compose_traefik_provider.py -q && ruff check .`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A backend/app/core/traffic/kubernetes_traffic_router.py backend/app/api/deps.py backend/app/api/app.py backend/app/core/__init__.py backend/app/core/traffic/__init__.py backend/app/core/traffic/traffic_router.py README.md .env.example AGENTS.md backend/tests/test_traffic_router_config.py
git commit -m "feat(routing): remove unsupported Kubernetes router option"
```

---

### Task 2: F04 — ORM models and migration for externalized state

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/0025_externalized_state.py`
- Test: `backend/tests/test_externalized_state_models.py`

**Interfaces:**
- Consumes: `Base` from `app.db.base`.
- Produces: ORM models `DeployJobRecord`, `TrafficRouteRecord`, `WsTicketRecord`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_externalized_state_models.py`

```python
import uuid
import pytest
from sqlalchemy import select

from app.db.models import DeployJobRecord, TrafficRouteRecord, WsTicketRecord


@pytest.mark.asyncio
async def test_deploy_job_record_round_trip(quota_db) -> None:
    record = DeployJobRecord(
        job_id="abc123", kind="container", project_id=uuid.uuid4(), user_id=uuid.uuid4(),
        name="web", status="in_progress", phase="queued", services=[{"name": "web", "state": "pending"}],
    )
    quota_db.add(record)
    await quota_db.commit()
    loaded = (await quota_db.execute(select(DeployJobRecord))).scalar_one()
    assert loaded.job_id == "abc123"
    assert loaded.services == [{"name": "web", "state": "pending"}]


@pytest.mark.asyncio
async def test_traffic_route_and_ws_ticket_records(quota_db) -> None:
    quota_db.add(TrafficRouteRecord(
        route_id="web-route", host="web.example", path_prefix="/", backend_servers=["http://web:80"],
        tls_enabled=False, entrypoints=["web"],
    ))
    quota_db.add(WsTicketRecord(ticket="ticket-1", container_id="c1", purpose="logs"))
    await quota_db.commit()
    assert len((await quota_db.execute(select(TrafficRouteRecord))).scalars().all()) == 1
    assert len((await quota_db.execute(select(WsTicketRecord))).scalars().all()) == 1
```

Reuse the `quota_db` fixture by importing it from `tests.test_compute_quota` or defining the same in-memory `StaticPool` fixture locally.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_externalized_state_models.py -q`
Expected: FAIL — models not found.

- [ ] **Step 3: Add the models** to `backend/app/db/models.py`

```python
class DeployJobRecord(Base):
    __tablename__ = "deploy_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_label: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress")
    phase: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    phase_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    services: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class TrafficRouteRecord(Base):
    __tablename__ = "traffic_routes"

    route_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    path_prefix: Mapped[str] = mapped_column(String(512), nullable=False, default="/")
    backend_servers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tls_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    entrypoints: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class WsTicketRecord(Base):
    __tablename__ = "ws_tickets"

    ticket: Mapped[str] = mapped_column(String(128), primary_key=True)
    container_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
```

Use the module's existing `_utcnow`, `Uuid`, `JSON`, `Boolean`, `Text`, `String` imports (add `Text` if missing).

- [ ] **Step 4: Create the migration** `backend/alembic/versions/0025_externalized_state.py`

```python
"""externalized state

Revision ID: 0025_externalized_state
Revises: 0024_api_token_lifecycle
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_externalized_state"
down_revision = "0024_api_token_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deploy_jobs",
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_label", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("phase", sa.String(64), nullable=False),
        sa.Column("phase_detail", sa.Text(), nullable=True),
        sa.Column("services", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_deploy_jobs_project_id", "deploy_jobs", ["project_id"])
    op.create_index("ix_deploy_jobs_finished_at", "deploy_jobs", ["finished_at"])

    op.create_table(
        "traffic_routes",
        sa.Column("route_id", sa.String(128), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("path_prefix", sa.String(512), nullable=False),
        sa.Column("backend_servers", sa.JSON(), nullable=False),
        sa.Column("tls_enabled", sa.Boolean(), nullable=False),
        sa.Column("entrypoints", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("route_id"),
    )

    op.create_table(
        "ws_tickets",
        sa.Column("ticket", sa.String(128), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("ticket"),
    )
    op.create_index("ix_ws_tickets_container_id", "ws_tickets", ["container_id"])


def downgrade() -> None:
    op.drop_index("ix_ws_tickets_container_id", table_name="ws_tickets")
    op.drop_table("ws_tickets")
    op.drop_table("traffic_routes")
    op.drop_index("ix_deploy_jobs_finished_at", table_name="deploy_jobs")
    op.drop_index("ix_deploy_jobs_project_id", table_name="deploy_jobs")
    op.drop_table("deploy_jobs")
```

- [ ] **Step 5: Run tests and migration check**

Run: `cd backend && python -m pytest tests/test_externalized_state_models.py -q && alembic upgrade head && alembic downgrade base && alembic upgrade head`
Expected: PASS, migration applies and reverts cleanly.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0025_externalized_state.py backend/tests/test_externalized_state_models.py
git commit -m "feat(state): add deploy job, traffic route and ws ticket tables"
```

---

### Task 3: F04 — DB-backed deploy job registry and async call sites

**Files:**
- Modify: `backend/app/core/deploy/jobs.py`, `backend/app/api/app.py`, `backend/app/api/deps.py`, `backend/app/api/routes/deploys.py`, `backend/app/api/routes/containers.py`, `backend/app/api/routes/stacks.py`, `backend/app/core/stacks/deploy.py`, `backend/tests/conftest.py`, `backend/tests/test_deploy_jobs.py`
- Test: `backend/tests/test_deploy_jobs.py` (rewritten fixtures), `frontend/e2e/deploy-progress.spec.ts` (unchanged, run as check)

**Interfaces:**
- Consumes: `DeployJobRecord`, `get_db_session_factory`.
- Produces: `DeployJobRegistry(session_factory)` with **async** `create`, `get`, `set_phase`, `set_services`, `set_service_state`, `complete_success`, `complete_failure`, `active`; unchanged `spawn`/`cancel_all`.

- [ ] **Step 1: Rewrite the registry** in `backend/app/core/deploy/jobs.py`

Keep `classify_deploy_error`, `DeployServiceProgress`, `DeployJob`, the status literals and `TERMINAL_JOB_TTL` unchanged. Replace `DeployJobRegistry` with:

```python
class DeployJobRegistry:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def create(self, *, kind: DeployJobKind, project_id: uuid.UUID, user_id: uuid.UUID,
                     name: str, source_label: str = "", services: list[str] | None = None) -> DeployJob:
        job = DeployJob(
            kind=kind, project_id=project_id, user_id=user_id, name=name,
            source_label=source_label,
            services=[DeployServiceProgress(name=item) for item in (services or [])],
        )
        async with self._session_factory() as session:
            session.add(self._to_record(job))
            await session.commit()
        return job

    async def get(self, job_id: str) -> DeployJob | None:
        async with self._session_factory() as session:
            record = await session.get(DeployJobRecord, job_id)
            return self._from_record(record) if record else None

    async def _update(self, job_id: str, change: Callable[[DeployJobRecord], None]) -> None:
        async with self._session_factory() as session:
            record = await session.get(DeployJobRecord, job_id)
            if record is None:
                return
            change(record)
            await session.commit()

    async def set_phase(self, job_id: str, phase: str, phase_detail: str | None = None) -> None:
        await self._update(job_id, lambda record: setattr(record, "phase", phase) or setattr(record, "phase_detail", phase_detail))

    async def set_services(self, job_id: str, names: list[str]) -> None:
        await self._update(job_id, lambda record: setattr(record, "services", [{"name": name, "state": "pending"} for name in names]))

    async def set_service_state(self, job_id: str, service_name: str, state: str) -> None:
        def change(record: DeployJobRecord) -> None:
            record.services = [
                {**item, "state": state} if item.get("name") == service_name else item
                for item in record.services
            ]
        await self._update(job_id, change)

    async def complete_success(self, job_id: str, result: dict[str, Any]) -> None:
        def change(record: DeployJobRecord) -> None:
            if record.status == "in_progress":
                record.status, record.result, record.finished_at = "succeeded", result, datetime.now(UTC)
        await self._update(job_id, change)

    async def complete_failure(self, job_id: str, error: dict[str, Any]) -> None:
        def change(record: DeployJobRecord) -> None:
            if record.status == "in_progress":
                record.status, record.error, record.finished_at = "failed", error, datetime.now(UTC)
        await self._update(job_id, change)

    async def active(self, *, project_ids: set[uuid.UUID]) -> list[DeployJob]:
        async with self._session_factory() as session:
            await session.execute(
                delete(DeployJobRecord).where(
                    DeployJobRecord.finished_at.is_not(None),
                    DeployJobRecord.finished_at < datetime.now(UTC) - timedelta(seconds=TERMINAL_JOB_TTL),
                )
            )
            rows = (await session.execute(
                select(DeployJobRecord).where(DeployJobRecord.project_id.in_(project_ids))
            )).scalars().all()
            await session.commit()
            return [self._from_record(row) for row in rows]

    def spawn(self, job_id: str, coro: Coroutine[Any, Any, None]) -> None:  # unchanged body
        ...

    async def cancel_all(self) -> None:  # unchanged body
        ...

    @staticmethod
    def _to_record(job: DeployJob) -> DeployJobRecord: ...
    @staticmethod
    def _from_record(record: DeployJobRecord) -> DeployJob: ...
```

Implement `_to_record`/`_from_record` explicitly, mapping `services` to/from `list[dict[str, str]]` and copying every scalar field including `created_at` and `finished_at`.

- [ ] **Step 2: Construct the registry with the session factory** in `backend/app/api/app.py`:

```python
    deploy_jobs = DeployJobRegistry(get_db_session_factory())
    _application.state.deploy_jobs = deploy_jobs
```

`deps.get_deploy_jobs` stays unchanged. Update the module docstring in `jobs.py` to say jobs are persisted in Postgres with a 300 s terminal TTL sweep on `active()`.

- [ ] **Step 3: Convert call sites to `await`**

- `backend/app/api/routes/deploys.py`: `jobs = await registry.active(project_ids=accessible)`.
- `backend/app/api/routes/containers.py`: add `await` to all 14 registry calls at lines 884, 918, 922, 951, 973, 1003, 1007, 1038, 1062, 1100, 1104, 1133, 1147 and `await registry.create(...)` at 1204 / `await registry.set_phase(...)` at 1211.
- `backend/app/api/routes/stacks.py`: same for lines 293, 309, 321-324, 327, 341, 343, 388, 396.

- [ ] **Step 4: Convert the sync stack callbacks** in `backend/app/core/stacks/deploy.py`:

```python
    on_phase: Callable[[str, str | None], Awaitable[None]] | None = None,
    on_service_state: Callable[[str, str], Awaitable[None]] | None = None,
```

At all six invocation sites (lines 85-86, 92-93, 108-109, 145-146, 161-162, 180-181) change to `await on_phase(...)` / `await on_service_state(...)` guarded by `if on_phase is not None`. In `stacks.py` the existing `lambda phase, _detail: registry.set_phase(job_id, phase)` still works because the lambda returns a coroutine that is now awaited; keep it.

- [ ] **Step 5: Rewrite test fixtures** in `backend/tests/test_deploy_jobs.py`

Replace `_registry() -> DeployJobRegistry` with an async fixture built from `db_session_factory` (from conftest):

```python
@pytest_asyncio.fixture
async def registry(db_session_factory) -> DeployJobRegistry:
    return DeployJobRegistry(db_session_factory)
```

Add `await` to every registry call in the unit tests, replace the direct `job.finished_at = ...` TTL test with a DB update through a session, and add a `deploy_jobs` parameter to `tests.conftest._build_app_with_overrides` so API tests can pass the DB-backed registry. Keep `wait_for_deploy()` and all HTTP assertions unchanged.

- [ ] **Step 6: Verify**

Run:
```bash
cd backend && python -m pytest tests/test_deploy_jobs.py tests/test_api_integration.py tests/test_deploy_epic.py tests/test_stack_permissions.py -q && ruff check . && mypy app/ tests/
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/deploy/jobs.py backend/app/api/app.py backend/app/api/routes/deploys.py backend/app/api/routes/containers.py backend/app/api/routes/stacks.py backend/app/core/stacks/deploy.py backend/tests/conftest.py backend/tests/test_deploy_jobs.py
git commit -m "feat(state): persist deploy jobs in Postgres"
```

---

### Task 4: F04 — DB-backed traffic router and state importer

**Files:**
- Create: `backend/app/core/traffic/database_traffic_router.py`, `backend/import_traffic_state.py`
- Modify: `backend/app/api/deps.py`, `.env.example`, `docker-compose.yml`
- Test: `backend/tests/test_database_traffic_router.py`, `backend/tests/test_import_traffic_state.py`

**Interfaces:**
- Consumes: `TrafficRouteRecord`, `RouteSpec`, `RouteInfo`, helpers from `traefik_file_traffic_router.py`.
- Produces: `DatabaseTrafficRouter`, selected by `VELA_TRAFFIC_STATE_BACKEND=postgres`; `import_traffic_state(file_path, session_factory, dynamic_file)`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_database_traffic_router.py`

```python
from uuid import uuid4
import pytest
from app.core.enums import RouteProtocol
from app.core.traffic.database_traffic_router import DatabaseTrafficRouter
from app.core.traffic.traffic_models import BackendServer, RouteSpec


@pytest.fixture
def router(tmp_path, db_session_factory):
    return DatabaseTrafficRouter(
        session_factory=db_session_factory,
        traefik_dynamic_file=tmp_path / "traefik-http.yml",
    )


def _spec(host: str) -> RouteSpec:
    return RouteSpec(
        route_id=uuid4().hex,
        host=host,
        path_prefix="/",
        backend_servers=[BackendServer(url="http://web:80")],
        tls_enabled=False,
        entrypoints=["web"],
    )


@pytest.mark.asyncio
async def test_upsert_get_remove_round_trip(router) -> None:
    spec = _spec("web.example")
    info = await router.upsert_route(spec)
    assert info.route_id == spec.route_id
    assert (await router.get_route(spec.route_id)).host == "web.example"
    assert len(await router.list_routes()) == 1
    await router.remove_route(spec.route_id)
    assert await router.list_routes() == []


@pytest.mark.asyncio
async def test_upsert_regenerates_traefik_document(router) -> None:
    spec = _spec("web.example")
    await router.upsert_route(spec)
    content = router.traefik_dynamic_file.read_text(encoding="utf-8")
    assert "web.example" in content
```

Use the exact `RouteSpec`/`BackendServer` field names from `backend/app/core/traffic/traffic_models.py` (the sample above follows the documented `host`, `path_prefix`, `backend_servers`, `tls_enabled`, `entrypoints` shape; adjust the `BackendServer` field to its real name if it is `url` vs `address`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_database_traffic_router.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `backend/app/core/traffic/database_traffic_router.py`**

```python
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import RouteNotFoundError, TrafficRouterError
from app.core.traffic.traffic_models import RouteInfo, RouteSpec
from app.core.traffic.traefik_file_traffic_router import (
    _atomic_write_bytes,
    _build_traefik_document,
    _reload_traefik_container_sighup,
)
from app.core.traffic.traffic_router import TrafficRouter
from app.db.models import TrafficRouteRecord


class DatabaseTrafficRouter(TrafficRouter):
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession],
                 traefik_dynamic_file: Path, reload_container: str | None = None) -> None:
        self._session_factory = session_factory
        self.traefik_dynamic_file = traefik_dynamic_file.resolve()
        self._reload_container = reload_container
        self._lock = asyncio.Lock()

    async def _all_specs(self, session: AsyncSession) -> list[RouteSpec]:
        rows = (await session.execute(select(TrafficRouteRecord))).scalars().all()
        return [RouteSpec(
            route_id=row.route_id, host=row.host, path_prefix=row.path_prefix,
            backend_servers=row.backend_servers, tls_enabled=row.tls_enabled,
            entrypoints=row.entrypoints,
        ) for row in rows]

    async def _write_document(self, specs: list[RouteSpec]) -> None:
        document = _build_traefik_document(specs)
        import json
        await asyncio.to_thread(
            _atomic_write_bytes, self.traefik_dynamic_file,
            json.dumps(document, indent=2, sort_keys=True).encode("utf-8"),
        )
        if self._reload_container:
            _reload_traefik_container_sighup(self._reload_container)

    async def upsert_route(self, spec: RouteSpec) -> RouteInfo:
        async with self._lock:
            async with self._session_factory() as session:
                record = await session.get(TrafficRouteRecord, spec.route_id)
                if record is None:
                    session.add(TrafficRouteRecord(
                        route_id=spec.route_id, host=spec.host, path_prefix=spec.path_prefix,
                        backend_servers=spec.backend_servers, tls_enabled=spec.tls_enabled,
                        entrypoints=spec.entrypoints,
                    ))
                else:
                    record.host, record.path_prefix = spec.host, spec.path_prefix
                    record.backend_servers, record.tls_enabled = spec.backend_servers, spec.tls_enabled
                    record.entrypoints = spec.entrypoints
                await session.commit()
                await self._write_document(await self._all_specs(session))
        return RouteInfo.from_spec(spec)

    async def remove_route(self, route_id: str) -> None:
        async with self._lock:
            async with self._session_factory() as session:
                record = await session.get(TrafficRouteRecord, route_id)
                if record is None:
                    raise RouteNotFoundError(f"Route {route_id} not found")
                await session.delete(record)
                await session.commit()
                await self._write_document(await self._all_specs(session))

    async def get_route(self, route_id: str) -> RouteInfo:
        async with self._session_factory() as session:
            record = await session.get(TrafficRouteRecord, route_id)
            if record is None:
                raise RouteNotFoundError(f"Route {route_id} not found")
            spec = RouteSpec(
                route_id=record.route_id, host=record.host, path_prefix=record.path_prefix,
                backend_servers=record.backend_servers, tls_enabled=record.tls_enabled,
                entrypoints=record.entrypoints,
            )
            return RouteInfo.from_spec(spec)

    async def list_routes(self) -> list[RouteInfo]:
        async with self._session_factory() as session:
            return [RouteInfo.from_spec(spec) for spec in await self._all_specs(session)]
```

- [ ] **Step 4: Select the DB router by env** in `backend/app/api/deps.py`

Add `from app.core.traffic.database_traffic_router import DatabaseTrafficRouter` and extend `_traffic_router_from_env()`:

```python
    if mode == "traefik_file":
        dynamic_file = Path(...)
        if os.getenv("VELA_TRAFFIC_STATE_BACKEND", "").strip() == "postgres":
            return DatabaseTrafficRouter(
                session_factory=get_db_session_factory(),
                traefik_dynamic_file=dynamic_file,
                reload_container=os.getenv("VELA_TRAEFIK_RELOAD_CONTAINER") or None,
            )
        return TraefikFileTrafficRouter(...)
```

Declare `VELA_TRAFFIC_STATE_BACKEND=` in `.env.example` next to the Traefik settings with a comment that `postgres` enables the multi-replica state store.

- [ ] **Step 5: Add the importer** `backend/import_traffic_state.py`

```python
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.traffic.traffic_models import RouteSpec
from app.core.traffic.traefik_file_traffic_router import _build_traefik_document, _atomic_write_bytes
from app.db.engine import get_session_factory
from app.db.models import TrafficRouteRecord


async def import_traffic_state(
    file_path: Path, session_factory: async_sessionmaker[AsyncSession], dynamic_file: Path,
) -> int:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    specs = [RouteSpec.model_validate(item) for item in payload["routes"]]
    async with session_factory() as session:
        for spec in specs:
            existing = await session.get(TrafficRouteRecord, spec.route_id)
            if existing is None:
                session.add(TrafficRouteRecord(
                    route_id=spec.route_id, host=spec.host, path_prefix=spec.path_prefix,
                    backend_servers=spec.backend_servers, tls_enabled=spec.tls_enabled,
                    entrypoints=spec.entrypoints,
                ))
        await session.commit()
        rows = (await session.execute(select(TrafficRouteRecord))).scalars().all()
    document = _build_traefik_document([
        RouteSpec(route_id=row.route_id, host=row.host, path_prefix=row.path_prefix,
                  backend_servers=row.backend_servers, tls_enabled=row.tls_enabled,
                  entrypoints=row.entrypoints)
        for row in rows
    ])
    await asyncio.to_thread(
        _atomic_write_bytes, dynamic_file,
        json.dumps(document, indent=2, sort_keys=True).encode("utf-8"),
    )
    return len(specs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--dynamic-file", required=True, type=Path)
    args = parser.parse_args()
    count = asyncio.run(import_traffic_state(args.file, get_session_factory(), args.dynamic_file))
    print(f"Imported {count} routes")


if __name__ == "__main__":
    main()
```

Add `from sqlalchemy import select` to the imports. Write `backend/tests/test_import_traffic_state.py` with a `tmp_path` sidecar containing one `RouteSpec.model_dump(mode="json")` and a `db_session_factory`, asserting the importer is idempotent when called twice.

- [ ] **Step 6: Verify**

Run: `cd backend && python -m pytest tests/test_database_traffic_router.py tests/test_import_traffic_state.py tests/test_route_wiring.py -q && ruff check .`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/traffic/database_traffic_router.py backend/import_traffic_state.py backend/app/api/deps.py .env.example backend/tests/test_database_traffic_router.py backend/tests/test_import_traffic_state.py
git commit -m "feat(state): add Postgres traffic state store and importer"
```

---

### Task 5: F04 — DB-backed WebSocket tickets and compose R2 default

**Files:**
- Modify: `backend/app/core/containers/ws_tickets.py`, `docker-compose.yml`, `.env.example`
- Test: `backend/tests/test_ws_tickets.py`

**Interfaces:**
- Consumes: `WsTicketRecord`, `get_db_session_factory`.
- Produces: `issue_ws_ticket` / `consume_ws_ticket` backed by Postgres; compose `api` service defaults `VELA_OBJECT_STORAGE=r2`.

- [ ] **Step 1: Write a failing test** in `backend/tests/test_ws_tickets.py`

```python
from app.core.containers.ws_tickets import consume_ws_ticket, issue_ws_ticket
from app.db.models import WsTicketRecord


def test_ticket_can_be_consumed_once(db_session_factory) -> None:
    ticket = issue_ws_ticket(session_factory=db_session_factory, container_id="c1", purpose="logs")
    assert consume_ws_ticket(session_factory=db_session_factory, ticket=ticket) == ("c1", "logs")
    assert consume_ws_ticket(session_factory=db_session_factory, ticket=ticket) is None
```

Match the exact existing signatures in `ws_tickets.py` and adjust the call shape in the test rather than changing the public API more than needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ws_tickets.py -q`
Expected: FAIL — signature mismatch or process-local behaviour.

- [ ] **Step 3: Move ticket state to Postgres** in `backend/app/core/containers/ws_tickets.py`

Replace the process-local dict with inserts/deletes on `WsTicketRecord`, using `secrets.token_urlsafe(32)` for the ticket and a short TTL check against `created_at` on consume. Keep the public function names and the one-shot semantics. Delete expired rows on consume (the same lazy-sweep pattern as deploy jobs).

- [ ] **Step 4: Update the WebSocket routes** in `backend/app/api/routes/containers.py` if ticket issuance/consumption now needs a session factory — inject `get_db_session_factory` at the two WS ticket call sites and pass it through. No WebSocket protocol or URL changes.

- [ ] **Step 5: Set compose defaults**

In `docker-compose.yml` api `environment`, add:

```yaml
      VELA_OBJECT_STORAGE: ${VELA_OBJECT_STORAGE:-r2}
      VELA_R2_ACCOUNT_ID: ${VELA_R2_ACCOUNT_ID:-}
      VELA_R2_ACCESS_KEY_ID: ${VELA_R2_ACCESS_KEY_ID:-}
      VELA_R2_SECRET_ACCESS_KEY: ${VELA_R2_SECRET_ACCESS_KEY:-}
      VELA_R2_BUCKET: ${VELA_R2_BUCKET:-}
      VELA_R2_PUBLIC_BASE_URL: ${VELA_R2_PUBLIC_BASE_URL:-}
```

Keep `deps.py`'s `VELA_OBJECT_STORAGE` default as `memory` so pytest and direct runs are unchanged. Add a documented R2 block to `.env.example` with all five variables, noting `boto3` is already pinned and the public bucket must serve `VELA_R2_PUBLIC_BASE_URL/<key>`.

- [ ] **Step 6: Verify**

Run: `cd backend && python -m pytest tests/test_ws_tickets.py tests/test_profile.py -q && ruff check .`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/containers/ws_tickets.py backend/app/api/routes/containers.py docker-compose.yml .env.example backend/tests/test_ws_tickets.py
git commit -m "feat(state): persist websocket tickets and default compose storage to R2"
```

---

### Task 6: F04 — opt-in HA compose profile and verification

**Files:**
- Modify: `docker-compose.yml`, `backend/app/api/app.py`, `.env.example`, `README.md`
- Test: `backend/tests/test_compose_ha_profile.py`

**Interfaces:**
- Consumes: `VELA_BACKGROUND_LOOPS_ENABLED`.
- Produces: compose services `api-ha` (replicas) and `scheduler` (single replica, loops enabled), both under profile `ha`.

- [ ] **Step 1: Write a failing contract test** in `backend/tests/test_compose_ha_profile.py`

```python
from pathlib import Path
import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def test_ha_profile_services_exist() -> None:
    config = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = config["services"]
    assert services["api-ha"]["profiles"] == ["ha"]
    assert services["scheduler"]["profiles"] == ["ha"]
    assert services["api-ha"]["environment"]["VELA_BACKGROUND_LOOPS_ENABLED"] == "0"
    assert services["scheduler"]["environment"]["VELA_BACKGROUND_LOOPS_ENABLED"] == "1"
    assert "api" not in config["services"]["api"].get("profiles", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_compose_ha_profile.py -q`
Expected: FAIL — KeyError on `api-ha`.

- [ ] **Step 3: Gate the background loops** in `backend/app/api/app.py`

Wrap the monitor/metrics/scaling/log-collector startup block (lines 68-103) in:

```python
    if os.getenv("VELA_BACKGROUND_LOOPS_ENABLED", "1") == "1":
        # existing loop startup, unchanged
        ...
```

Shutdown code must cancel only tasks that were actually created; keep an empty list otherwise. Add `import os` if missing.

- [ ] **Step 4: Add the HA services** to `docker-compose.yml`

```yaml
  api-ha:
    profiles: ["ha"]
    build: { context: ./backend, dockerfile: Dockerfile }
    image: vela/api
    env_file: .env
    environment:
      VELA_BACKGROUND_LOOPS_ENABLED: "0"
      VELA_TRAFFIC_STATE_BACKEND: postgres
      VELA_OBJECT_STORAGE: r2
    volumes: *api_volumes
    networks: *api_networks
    healthcheck: *api_healthcheck
    depends_on:
      migrate: { condition: service_completed_successfully }
    restart: unless-stopped
    deploy:
      replicas: ${VELA_API_REPLICAS:-3}

  scheduler:
    profiles: ["ha"]
    image: vela/api
    env_file: .env
    environment:
      VELA_BACKGROUND_LOOPS_ENABLED: "1"
      VELA_TRAFFIC_STATE_BACKEND: postgres
    volumes: *api_volumes
    networks: *api_networks
    depends_on:
      migrate: { condition: service_completed_successfully }
    restart: unless-stopped
```

Copy the `volumes`, `networks` and `healthcheck` blocks verbatim from the existing `api` service (`docker-compose.yml:88-106`) into both new services; do not add `container_name` to either service. Add `VELA_BACKGROUND_LOOPS_ENABLED=1` and `VELA_API_REPLICAS=3` to `.env.example` with comments explaining the `ha` profile. Document the profile briefly in `README.md` next to the deploy section.

- [ ] **Step 5: Verify the compose stack** per `AGENTS.md`

Run:
```bash
cd backend && python -m pytest tests/test_compose_ha_profile.py tests/test_compose_traefik_provider.py -q && ruff check .
cd .. && docker compose -f docker-compose.yml config -q
docker compose --profile ha config -q
docker compose up -d --build
docker compose ps
docker compose down
docker compose --profile ha up -d --build
docker compose ps
docker compose down
```
Expected: all config checks pass; `migrate` exits completed and `api` reaches `healthy` in both default and `--profile ha` runs. If R2 credentials are absent in the smoke environment, set `VELA_OBJECT_STORAGE=memory` for the smoke run only and note that the HA profile's R2 requirement remains documented.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml backend/app/api/app.py .env.example README.md backend/tests/test_compose_ha_profile.py
git commit -m "feat(infra): add opt-in multi-replica compose profile"
```

---

## Self-review (done at plan authoring)

- **Spec coverage:** F17 → Task 1; F04 job state → Tasks 2–3; traffic state → Task 4; object storage → Task 5; stateless multi-replica → Tasks 5–6. Single-node compose is untouched by default; multi-replica is opt-in.
- **Placeholder scan:** no TBD/TODO. Task 4 Step 1 notes one field-name check against `traffic_models.py`, and Task 5 Step 1 notes matching the existing `ws_tickets.py` signature; both are exact-location checks, not deferred work.
- **Type consistency:** `DeployJobRegistry` async signatures defined in Task 3 are used by all callers in the same task; `TrafficRouteRecord` and `WsTicketRecord` from Task 2 are used by Tasks 4–5; `validate_traffic_router_config` from Task 1 is called in `create_app()`.
