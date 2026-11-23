# Group A — Observability & limits (F02, F03, F09, F18) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a token-protected Prometheus scrape with a shared edge request counter, hard-fail per-team compute quotas, resource-time showback, and RPS scaling fed by that counter.

**Architecture:** One shared core module (`app/core/monitoring/edge_requests.py`) parses an opt-in Traefik JSON access log and exposes per-host request rates plus an availability flag; both `/metrics` and the scaling engine call it. Compute quotas live in a new `app/core/quotas/compute_quota.py` mirroring `storage_quota.py`, enforced at both API deploy admission points and the scaling engine's replica-deploy path, with an alembic migration adding nullable ceiling columns to `projects`. Showback reuses `/api/metrics/usage` aggregation; CSV follows the existing logs-export pattern. A dedicated exception maps compute-quota admission to HTTP 409 (the storage precedent maps to 400, which this feature deliberately does not copy).

**Tech Stack:** FastAPI, SQLAlchemy async, Postgres/Alembic, pytest + `TestClient`, React/TypeScript, Recharts, Playwright.

## Global Constraints

- Worktree root: `C:\Users\lolo\.local\share\opencode\worktree\ab1b01\defect-remediation`. Paths are relative to it.
- MVC: domain logic in `backend/app/core/`, schemas in `backend/app/api/schemas.py`, thin handlers in `backend/app/api/routes/`.
- Backend verification per task: `cd backend && python -m pytest tests -q` (env: `VELA_FAKE_ORCHESTRATOR=1`, `VELA_DATABASE_URL=sqlite+aiosqlite:///:memory:`) and `ruff check . && mypy app/ tests/`.
- Frontend verification: `cd frontend && npm run typecheck && npm run lint && npm run build`; E2E with `npm run test:e2e -- <spec>` after the UI tasks.
- Exact dependency versions only; no new frontend/runtime dependency.
- `DeployConfig.cpu_limit` is **cores**, `memory_limit` is **MB** — convert to millicores (×1000) and bytes (×1024²) once, in `compute_quota.py`.
- Never substitute CPU for `REQUESTS_PER_SECOND` except for the `noop` router, which must stay documented as a proxy.
- New page-specific CSS goes in a new `.css` file imported by the page; never grow `index.css`.

---

### Task 1: F02/F18 shared edge request counter

**Files:**
- Create: `backend/app/core/monitoring/edge_requests.py`
- Test: `backend/tests/test_edge_requests.py`

**Interfaces:**
- Consumes: Traefik JSON access log lines with `StartUTC` (ISO timestamp) and `RequestHost`/`RouterName`, path from `VELA_EDGE_ACCESS_LOG_PATH`.
- Produces: `EdgeRequestRates(rates_by_host: dict[str, float], available: bool)` and `get_edge_request_rates(window_seconds: int = 60) -> EdgeRequestRates`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_edge_requests.py`

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.monitoring.edge_requests import get_edge_request_rates, reset_edge_request_cache


def _line(host: str, when: datetime) -> str:
    return json.dumps({
        "StartUTC": when.isoformat().replace("+00:00", "Z"),
        "RequestHost": host,
        "RouterName": "router-" + host,
    })


def test_counts_requests_per_host_in_rolling_window(tmp_path: Path, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    log = tmp_path / "access.log"
    log.write_text("\n".join([
        _line("a.example", now - timedelta(seconds=5)),
        _line("a.example", now - timedelta(seconds=10)),
        _line("b.example", now - timedelta(seconds=8)),
        _line("a.example", now - timedelta(hours=2)),
    ]), encoding="utf-8")
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", str(log))
    reset_edge_request_cache()
    result = get_edge_request_rates(window_seconds=60)
    assert result.available is True
    assert round(result.rates_by_host["a.example"], 4) == round(2 / 60, 4)
    assert round(result.rates_by_host["b.example"], 4) == round(1 / 60, 4)


def test_unavailable_without_configured_log(monkeypatch) -> None:
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", "")
    reset_edge_request_cache()
    result = get_edge_request_rates()
    assert result.available is False
    assert result.rates_by_host == {}


def test_malformed_lines_are_ignored(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "access.log"
    log.write_text("not json\n" + _line("a.example", datetime.now(timezone.utc)) + "\n", encoding="utf-8")
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", str(log))
    reset_edge_request_cache()
    assert list(get_edge_request_rates().rates_by_host) == ["a.example"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_edge_requests.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Create `backend/app/core/monitoring/edge_requests.py`**

```python
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdgeRequestRates:
    rates_by_host: dict[str, float]
    available: bool


_CACHE_TTL_SECONDS = 5
_cache: tuple[float, EdgeRequestRates] | None = None


def reset_edge_request_cache() -> None:
    global _cache
    _cache = None


def _configured_path() -> Path | None:
    configured = os.getenv("VELA_EDGE_ACCESS_LOG_PATH", "").strip()
    return Path(configured) if configured else None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_rates(path: Path, window_seconds: int) -> dict[str, float]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    counts: dict[str, int] = defaultdict(int)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                timestamp = _parse_timestamp(entry.get("StartUTC"))
                if timestamp is None or timestamp < cutoff:
                    continue
                host = entry.get("RequestHost") or entry.get("RouterName")
                if isinstance(host, str) and host:
                    counts[host] += 1
    except OSError:
        logger.warning("Cannot read edge access log at %s", path)
        return {}
    return {host: count / window_seconds for host, count in counts.items()}


def get_edge_request_rates(window_seconds: int = 60) -> EdgeRequestRates:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    path = _configured_path()
    if path is None:
        result = EdgeRequestRates(rates_by_host={}, available=False)
    else:
        rates = _read_rates(path, window_seconds)
        result = EdgeRequestRates(rates_by_host=rates, available=True)
    _cache = (now, result)
    return result
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_edge_requests.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/monitoring/edge_requests.py backend/tests/test_edge_requests.py
git commit -m "feat(metrics): add edge request rate counter"
```

---

### Task 2: F02 Prometheus scrape endpoint and compose access log

**Files:**
- Create: `backend/app/api/routes/prometheus.py`
- Modify: `backend/app/api/app.py`, `backend/app/api/errors.py`, `.env.example`, `docker-compose.yml`, `backend/tests/test_compose_traefik_provider.py`
- Test: `backend/tests/test_prometheus_api.py`

**Interfaces:**
- Consumes: `get_edge_request_rates` from Task 1; `list_accessible_project_ids`, `Project`, `ContainerMetric`, `DeploymentRecord`.
- Produces: `GET /metrics` returning `text/plain; version=0.0.4`, guarded by `VELA_METRICS_TOKEN`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_prometheus_api.py`

```python
from fastapi.testclient import TestClient


def test_metrics_requires_configured_token(api_client, monkeypatch) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "scrape-secret")
    app = api_client.app
    response = TestClient(app).get("/metrics")
    assert response.status_code == 401


def test_metrics_reports_platform_and_project_signals(api_client, monkeypatch) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "scrape-secret")
    response = TestClient(api_client.app).get(
        "/metrics", headers={"Authorization": "Bearer scrape-secret"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "vela_api_up 1" in body
    assert "vela_workloads_by_state" in body
    assert "# TYPE vela_deploy_success_rate gauge" in body


def test_metrics_disabled_without_token(api_client, monkeypatch) -> None:
    monkeypatch.setenv("VELA_METRICS_TOKEN", "")
    assert TestClient(api_client.app).get("/metrics").status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_prometheus_api.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Create `backend/app/api/routes/prometheus.py`**

```python
from __future__ import annotations

import os
import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_orchestrator
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import NotAuthenticatedError
from app.core.monitoring.edge_requests import get_edge_request_rates
from app.db.models import DeploymentRecord

router = APIRouter()


def require_metrics_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("VELA_METRICS_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Metrics scraping is not configured")
    provided = authorization.removeprefix("Bearer ") if authorization else ""
    if not secrets.compare_digest(provided, expected):
        raise NotAuthenticatedError("Invalid metrics token")


def _gauge(name: str, help_text: str, value: float, labels: dict[str, str] | None = None) -> list[str]:
    suffix = ""
    if labels:
        rendered = ",".join(f'{key}="{text}"' for key, text in labels.items())
        suffix = "{" + rendered + "}"
    return [f"# HELP {name} {help_text}", f"# TYPE {name} gauge", f"{name}{suffix} {value}"]


@router.get("/metrics", dependencies=[Depends(require_metrics_token)])
async def prometheus_metrics(
    session: AsyncSession = Depends(get_db),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
) -> PlainTextResponse:
    lines: list[str] = []
    lines += _gauge("vela_api_up", "API is serving requests", 1)
    edge = get_edge_request_rates()
    lines += _gauge("vela_edge_signal_available", "Edge request signal is available", 1 if edge.available else 0)
    for host, rate in sorted(edge.rates_by_host.items()):
        lines += _gauge("vela_edge_requests_per_second", "Requests per second at the edge", rate, {"host": host})

    containers = await orchestrator.list()
    states = Counter(info.status for info in containers)
    for state in ("running", "stopped", "failed"):
        lines += _gauge("vela_workloads_by_state", "Workloads by state", states.get(state, 0), {"state": state})

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    total = (await session.execute(
        select(DeploymentRecord).where(DeploymentRecord.created_at >= since)
    )).scalars().all()
    succeeded = sum(1 for record in total if record.container_id is not None)
    rate = succeeded / len(total) if total else 0.0
    lines += _gauge("vela_deploy_success_rate", "Fraction of recent deploys that produced a container", rate)
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
```

Keep per-project resource detail on the authenticated JSON API; this scrape exports only bounded platform aggregates.

- [ ] **Step 4: Wire the router in `backend/app/api/app.py`**

Add `prometheus` to the route-import block (lines 18-38) and register near the health endpoint:

```python
application.include_router(prometheus.router, tags=["prometheus"])
```

- [ ] **Step 5: Enable the opt-in Traefik access log in `docker-compose.yml`**

In the `traefik` service command list add:
```yaml
      - "--accesslog=true"
      - "--accesslog.filepath=/var/log/traefik/access.log"
      - "--accesslog.format=json"
```
Add a named volume `traefik_logs` to the top-level `volumes` and mount `traefik_logs:/var/log/traefik` in both the `traefik` and `api` services. In the `api` environment add:
```yaml
      VELA_EDGE_ACCESS_LOG_PATH: /var/log/traefik/access.log
      VELA_METRICS_TOKEN: ${VELA_METRICS_TOKEN:-}
```

- [ ] **Step 6: Declare env vars in `.env.example`** near the metrics section:

```ini
# Static bearer token for the Prometheus scrape endpoint (empty disables /metrics).
VELA_METRICS_TOKEN=

# Path to the Traefik JSON access log inside the API container (empty = edge signal unavailable).
VELA_EDGE_ACCESS_LOG_PATH=
```

- [ ] **Step 7: Verify the compose contract test still passes**

Run: `cd backend && python -m pytest tests/test_compose_traefik_provider.py -q`
Expected: PASS (assertions check for presence of existing strings).

- [ ] **Step 8: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_prometheus_api.py tests/test_edge_requests.py -q && ruff check .`

```bash
git add backend/app/api/routes/prometheus.py backend/app/api/app.py backend/tests/test_prometheus_api.py .env.example docker-compose.yml backend/tests/test_compose_traefik_provider.py
git commit -m "feat(metrics): add token-protected Prometheus scrape endpoint"
```

---

### Task 3: F03 compute quota core, schema, migration and errors

**Files:**
- Create: `backend/app/core/quotas/compute_quota.py`
- Modify: `backend/app/core/quotas/__init__.py`, `backend/app/core/exceptions.py`, `backend/app/api/errors.py`, `backend/app/db/models.py`, `.env.example`
- Create: `backend/alembic/versions/0026_add_team_compute_quotas.py`
- Test: `backend/tests/test_compute_quota.py`

**Interfaces:**
- Consumes: `Project`, `DeploymentRecord`, `load_deploy_config_snapshot`, `orchestrator.list()`, `list_accessible_project_ids`.
- Produces: `ComputeQuotaSummary`, `environment_compute_ceilings() -> dict[str, int | None]`, `team_compute_usage(session, orchestrator, project_id) -> ComputeQuotaUsage`, `enforce_team_compute_capacity(session, orchestrator, project_id) -> None`, `team_compute_quota_summary(session, orchestrator, project) -> ComputeQuotaSummary`.

- [ ] **Step 1: Add the exception types** to `backend/app/core/exceptions.py` next to the storage ones:

```python
class TeamComputeQuotaExceededError(ResourceLimitError):
    """A deploy or scale would push the team over its compute quota."""


class TeamComputeQuotaError(ResourceLimitError):
    """A compute quota value is invalid or above the platform ceiling."""
```

Add a 409 handler inside `register_exception_handlers` in `backend/app/api/errors.py`, next to `team_storage_quota_error_handler` (errors.py:243-251):

```python
    @app.exception_handler(TeamComputeQuotaExceededError)
    async def team_compute_quota_exceeded_handler(
        _request: Request, exc: TeamComputeQuotaExceededError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "code": "team_compute_quota_exceeded"},
        )
```

Add `TeamComputeQuotaExceededError` and `TeamComputeQuotaError` to that module's imports.

- [ ] **Step 2: Add nullable columns to `backend/app/db/models.py`** in `class Project` after `storage_quota_bytes`:

```python
    max_running_containers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_cpu_millicores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_memory_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_deploys_per_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 3: Create the pinned alembic migration** `backend/alembic/versions/0026_add_team_compute_quotas.py`

Create the file explicitly with the pinned revision id — do not use `alembic revision -m ...`, which auto-generates a random id parented on whatever head exists at run time and would fork the chain (Group C's `0027_group_c_lifecycle` pins `down_revision = "0026_add_team_compute_quotas"`):

```python
"""add team compute quotas

Revision ID: 0026_add_team_compute_quotas
Revises: 0025_externalized_state
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_add_team_compute_quotas"
down_revision = "0025_externalized_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("max_running_containers", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("max_cpu_millicores", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("max_memory_bytes", sa.BigInteger(), nullable=True))
    op.add_column("projects", sa.Column("max_deploys_per_hour", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "max_deploys_per_hour")
    op.drop_column("projects", "max_memory_bytes")
    op.drop_column("projects", "max_cpu_millicores")
    op.drop_column("projects", "max_running_containers")
```

- [ ] **Step 4: Write failing tests** in `backend/tests/test_compute_quota.py` (mirror `test_storage_quota.py` fixtures):

```python
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.containers.docker_orchestrator import VELA_PROJECT_LABEL
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator
from app.core.enums import ContainerStatus, HealthStatus
from app.core.exceptions import TeamComputeQuotaExceededError
from app.core.models import ContainerInfo, DeployConfig
from app.core.quotas.compute_quota import (
    enforce_team_compute_capacity,
    environment_compute_ceilings,
    team_compute_usage,
)
from app.db.base import Base
from app.db.models import DeploymentRecord, Organization, Project, User


@pytest_asyncio.fixture
async def quota_db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _info(project_id: uuid.UUID, container_id: str) -> ContainerInfo:
    return ContainerInfo(
        id=container_id,
        name="web",
        image="nginx",
        status=ContainerStatus.RUNNING,
        health=HealthStatus.HEALTHY,
        ports=[],
        labels={VELA_PROJECT_LABEL: str(project_id)},
        access_url=None,
        access_role=None,
        source_kind=None,
        source_label=None,
        created_at=datetime.now(UTC),
    )


async def _seed(session: AsyncSession, *, max_running: int | None = None) -> tuple[Project, str]:
    organization = Organization(name="compute org")
    session.add(organization)
    await session.flush()
    project = Project(
        organization_id=organization.id,
        name="Compute team",
        max_running_containers=max_running,
    )
    user = User(id=uuid.uuid4(), email="compute@example.com")
    session.add_all([project, user])
    await session.flush()
    container_id = "container-a"
    config = DeployConfig(
        image="nginx", name="web", cpu_limit=0.5, memory_limit=512, project_id=project.id,
    )
    session.add(DeploymentRecord(
        user_id=user.id,
        project_id=project.id,
        container_id=container_id,
        container_name="web",
        source_kind="image",
        source_ref="nginx",
        deploy_config=config.model_dump(mode="json"),
    ))
    await session.commit()
    return project, container_id


def test_ceilings_parse_and_clamp(monkeypatch) -> None:
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "10")
    monkeypatch.setenv("VELA_TEAM_MAX_CPU_MILLICORES", "4000")
    monkeypatch.setenv("VELA_TEAM_MAX_MEMORY_BYTES", "")
    monkeypatch.setenv("VELA_TEAM_MAX_DEPLOYS_PER_HOUR", "0")
    assert environment_compute_ceilings() == {
        "running_containers": 10,
        "cpu_millicores": 4000,
        "memory_bytes": None,
        "deploys_per_hour": None,
    }


@pytest.mark.asyncio
async def test_usage_converts_cores_and_mb(
    quota_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, container_id = await _seed(quota_db)
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "")
    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(_info(project.id, container_id))
    usage = await team_compute_usage(quota_db, orchestrator, project.id)
    assert usage.running_containers == 1
    assert usage.cpu_millicores == 500
    assert usage.memory_bytes == 512 * 1024**2


@pytest.mark.asyncio
async def test_enforcement_raises_when_over_quota(quota_db: AsyncSession) -> None:
    project, container_id = await _seed(quota_db, max_running=1)
    orchestrator = FakeContainerOrchestrator()
    orchestrator.seed_container(_info(project.id, container_id))
    with pytest.raises(TeamComputeQuotaExceededError) as excinfo:
        await enforce_team_compute_capacity(quota_db, orchestrator, project.id)
    assert "running containers" in str(excinfo.value)
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_compute_quota.py -q`
Expected: FAIL — module not found (and the two placeholder assertions fail).

- [ ] **Step 6: Implement `backend/app/core/quotas/compute_quota.py`**

```python
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deploy.deployment_history import load_deploy_config_snapshot
from app.core.containers.docker_orchestrator import VELA_PROJECT_LABEL
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import TeamComputeQuotaExceededError
from app.db.models import DeploymentRecord, Project


@dataclass(frozen=True)
class ComputeQuotaUsage:
    running_containers: int
    cpu_millicores: int
    memory_bytes: int
    deploys_per_hour: int


@dataclass(frozen=True)
class ComputeQuotaSummary:
    usage: ComputeQuotaUsage
    ceilings: dict[str, int | None]
    limits: dict[str, int | None]
    over_quota: dict[str, bool]


def _positive_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def environment_compute_ceilings() -> dict[str, int | None]:
    return {
        "running_containers": _positive_env("VELA_TEAM_MAX_RUNNING_CONTAINERS"),
        "cpu_millicores": _positive_env("VELA_TEAM_MAX_CPU_MILLICORES"),
        "memory_bytes": _positive_env("VELA_TEAM_MAX_MEMORY_BYTES"),
        "deploys_per_hour": _positive_env("VELA_TEAM_MAX_DEPLOYS_PER_HOUR"),
    }


def _effective_limits(project: Project) -> dict[str, int | None]:
    ceilings = environment_compute_ceilings()
    stored = {
        "running_containers": project.max_running_containers,
        "cpu_millicores": project.max_cpu_millicores,
        "memory_bytes": project.max_memory_bytes,
        "deploys_per_hour": project.max_deploys_per_hour,
    }
    return {
        key: min(value, ceilings[key]) if value is not None and ceilings[key] is not None
        else (value if ceilings[key] is None else ceilings[key])
        for key, value in stored.items()
    }


async def team_compute_usage(
    session: AsyncSession, orchestrator: ContainerOrchestrator, project_id: uuid.UUID,
) -> ComputeQuotaUsage:
    # Mirror usage_from_containers (storage_quota.py): orchestrator.list(project_ids=...)
    # only filters when user_id is also set, so list once and filter by label in Python.
    containers = await orchestrator.list()
    running = [
        info for info in containers
        if info.labels.get(VELA_PROJECT_LABEL) == str(project_id) and info.status == "running"
    ]
    cpu_millicores = 0
    memory_bytes = 0
    for info in running:
        config = await load_deploy_config_snapshot(session, info.id)
        if config is None:
            continue
        cpu_millicores += int((config.cpu_limit or 0.0) * 1000)
        memory_bytes += (config.memory_limit or 0) * 1024**2
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    deploys = (await session.execute(
        select(func.count(DeploymentRecord.id)).where(
            DeploymentRecord.project_id == project_id,
            DeploymentRecord.created_at >= since,
        )
    )).scalar_one()
    return ComputeQuotaUsage(len(running), cpu_millicores, memory_bytes, int(deploys))


async def enforce_team_compute_capacity(
    session: AsyncSession, orchestrator: ContainerOrchestrator, project_id: uuid.UUID,
) -> None:
    project = await session.get(Project, project_id)
    if project is None:
        return
    limits = _effective_limits(project)
    usage = await team_compute_usage(session, orchestrator, project_id)
    for key in ("running_containers", "cpu_millicores", "memory_bytes", "deploys_per_hour"):
        limit = limits[key]
        used = getattr(usage, key)
        if limit is not None and used >= limit:
            raise TeamComputeQuotaExceededError(
                f"Team compute quota exceeded for {key.replace('_', ' ')}: {used} used, limit {limit}"
            )


async def team_compute_quota_summary(
    session: AsyncSession, orchestrator: ContainerOrchestrator, project: Project,
) -> ComputeQuotaSummary:
    usage = await team_compute_usage(session, orchestrator, project.id)
    ceilings = environment_compute_ceilings()
    limits = _effective_limits(project)
    return ComputeQuotaSummary(
        usage=usage,
        ceilings=ceilings,
        limits=limits,
        over_quota={key: limits[key] is not None and getattr(usage, key) >= limits[key] for key in limits},
    )
```

- [ ] **Step 7: Re-export from `backend/app/core/quotas/__init__.py`**

```python
from .compute_quota import (
    ComputeQuotaSummary,
    ComputeQuotaUsage,
    enforce_team_compute_capacity,
    environment_compute_ceilings,
    team_compute_quota_summary,
    team_compute_usage,
)
```
Add those names to `__all__`.

- [ ] **Step 8: Declare the env ceilings in `.env.example`** next to `VELA_TEAM_STORAGE_QUOTA_BYTES`:

```ini
# Per-team compute ceilings (empty = unlimited; team settings can only restrict these).
VELA_TEAM_MAX_RUNNING_CONTAINERS=
VELA_TEAM_MAX_CPU_MILLICORES=
VELA_TEAM_MAX_MEMORY_BYTES=
VELA_TEAM_MAX_DEPLOYS_PER_HOUR=
```

- [ ] **Step 9: Run tests, lint and migration check**

Run:
```bash
cd backend
python -m pytest tests/test_compute_quota.py -q
alembic upgrade head
ruff check . && mypy app/ tests/
```
Expected: PASS; `alembic upgrade head` applies cleanly against a scratch DB.

- [ ] **Step 10: Commit**

```bash
git add backend/app/core/quotas/compute_quota.py backend/app/core/quotas/__init__.py backend/app/core/exceptions.py backend/app/api/errors.py backend/app/db/models.py backend/alembic/versions/0026_add_team_compute_quotas.py .env.example backend/tests/test_compute_quota.py
git commit -m "feat(quotas): add per-team compute quota core and migration"
```

---

### Task 4: F03 admission wiring and quota API

**Files:**
- Modify: `backend/app/api/routes/containers.py`, `backend/app/core/scaling/scaling_engine.py`, `backend/app/api/schemas.py`, `backend/app/api/routes/projects.py`
- Test: `backend/tests/test_compute_quota_api.py`, update `backend/tests/test_scaling_engine.py`

**Interfaces:**
- Consumes: `enforce_team_compute_capacity`, `team_compute_quota_summary`, `environment_compute_ceilings` from Task 3.
- Produces: `GET/PATCH /api/projects/{id}/compute-quota`, `ProjectComputeQuotaPublic`, `ProjectComputeQuotaUpdate`.

- [ ] **Step 1: Write failing API tests** in `backend/tests/test_compute_quota_api.py`

```python
from uuid import uuid4

from app.db.models import Project


def test_owner_can_set_compute_quota_within_ceiling(api_client, db_session_factory, monkeypatch):
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "20")
    project_id = uuid4()
    # seed Project + owner membership using the pattern from test_projects_api.py
    response = api_client.patch(
        f"/api/projects/{project_id}/compute-quota",
        json={"max_running_containers": 5},
    )
    assert response.status_code == 200
    assert response.json()["max_running_containers"] == 5


def test_member_cannot_set_compute_quota(other_user_client, db_session_factory):
    assert other_user_client.patch(f"/api/projects/{uuid4()}/compute-quota", json={"max_running_containers": 5}).status_code in (403, 404)


def test_quota_above_ceiling_is_rejected(api_client, db_session_factory, monkeypatch):
    monkeypatch.setenv("VELA_TEAM_MAX_RUNNING_CONTAINERS", "3")
    response = api_client.patch(f"/api/projects/{uuid4()}/compute-quota", json={"max_running_containers": 5})
    assert response.status_code == 400
```

Fill the seeding bodies with the exact `Project`/`ProjectMembership` setup from `backend/tests/test_projects_api.py` storage-quota tests before running.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_compute_quota_api.py -q`
Expected: FAIL — 404 on the new route.

- [ ] **Step 3: Add schemas** to `backend/app/api/schemas.py` next to `ProjectStorageQuotaUpdate`:

```python
class ProjectComputeQuotaPublic(BaseModel):
    max_running_containers: int | None
    max_cpu_millicores: int | None
    max_memory_bytes: int | None
    max_deploys_per_hour: int | None
    used_running_containers: int
    used_cpu_millicores: int
    used_memory_bytes: int
    used_deploys_per_hour: int
    platform_ceiling: dict[str, int | None]


class ProjectComputeQuotaUpdate(BaseModel):
    max_running_containers: int | None = Field(default=None, ge=1)
    max_cpu_millicores: int | None = Field(default=None, ge=1)
    max_memory_bytes: int | None = Field(default=None, ge=1)
    max_deploys_per_hour: int | None = Field(default=None, ge=1)
```

- [ ] **Step 4: Add routes** to `backend/app/api/routes/projects.py`, mirroring `_storage_quota_public`/`get_project_storage_quota`/`update_project_storage_quota`:

```python
@router.get("/{project_id}/compute-quota", response_model=ProjectComputeQuotaPublic)
async def get_project_compute_quota(project_id: uuid.UUID, orchestrator=Depends(get_orchestrator), current_user=Depends(get_current_user), session=Depends(get_db)):
    await require_membership(session, project_id=project_id, user_id=current_user.id)
    project = await require_project(session, project_id)
    summary = await team_compute_quota_summary(session, orchestrator, project)
    return ProjectComputeQuotaPublic(
        max_running_containers=project.max_running_containers,
        max_cpu_millicores=project.max_cpu_millicores,
        max_memory_bytes=project.max_memory_bytes,
        max_deploys_per_hour=project.max_deploys_per_hour,
        used_running_containers=summary.usage.running_containers,
        used_cpu_millicores=summary.usage.cpu_millicores,
        used_memory_bytes=summary.usage.memory_bytes,
        used_deploys_per_hour=summary.usage.deploys_per_hour,
        platform_ceiling=summary.ceilings,
    )


@router.patch("/{project_id}/compute-quota", response_model=ProjectComputeQuotaPublic)
async def update_project_compute_quota(project_id: uuid.UUID, body: ProjectComputeQuotaUpdate, orchestrator=Depends(get_orchestrator), current_user=Depends(get_current_user), session=Depends(get_db)):
    membership = await require_membership(session, project_id=project_id, user_id=current_user.id)
    if membership.role != ProjectRole.OWNER:
        raise ProjectAccessDeniedError("Only the team owner can change compute quotas")
    project = await require_project(session, project_id)
    ceilings = environment_compute_ceilings()
    for field, value in body.model_dump().items():
        if value is None:
            continue
        ceiling = ceilings[field.replace("max_", "")]
        if ceiling is not None and value > ceiling:
            raise TeamComputeQuotaError(f"{field} cannot exceed the platform ceiling of {ceiling}")
        setattr(project, field, value)
    await session.commit()
    return await get_project_compute_quota(project_id, orchestrator, current_user, session)
```

Use the route module's existing import aliases; the parameter annotations above are abbreviated — replace them with the exact `Annotated[...Depends(...)]` forms used by the neighbouring storage-quota handlers.

- [ ] **Step 5: Wire admission at both deploy paths** in `backend/app/api/routes/containers.py`:

Immediately after each existing `await enforce_team_storage_capacity(session, orchestrator, project_id)` (at the deploy route and the run-from-source route), add:

```python
    await enforce_team_compute_capacity(session, orchestrator, project_id)
```

- [ ] **Step 6: Wire admission into the scaling engine's replica deploy path** in `backend/app/core/scaling/scaling_engine.py`:

Inside `_scale_up(...)`, before the `orchestrator.deploy_replica(...)` call, add:

```python
    if base_config.project_id is not None:
        await enforce_team_compute_capacity(session, orchestrator, base_config.project_id)
```

`base_config` is the `DeployConfig` `_scale_up` already receives — do not add a second config parameter. Add a `session: AsyncSession` parameter to `_scale_up` and update **both** call sites: the positional call in `_evaluate_policy` (scaling_engine.py:315-324) and the existing keyword call in `tests/test_scaling_engine.py:49`.

- [ ] **Step 7: Run tests**

Run: `cd backend && python -m pytest tests/test_compute_quota_api.py tests/test_scaling_engine.py -q && ruff check .`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/routes/containers.py backend/app/core/scaling/scaling_engine.py backend/app/api/schemas.py backend/app/api/routes/projects.py backend/tests/test_compute_quota_api.py backend/tests/test_scaling_engine.py
git commit -m "feat(quotas): enforce compute quotas at deploy and scale"
```

---

### Task 5: F03 frontend — owner controls and usage-vs-quota panel

**Files:**
- Modify: `frontend/src/api/projects.ts`, `frontend/src/api/client.ts`, `frontend/src/pages/teams/useTeamManagement.ts`, `frontend/src/pages/teams/TeamDetail.tsx`, `frontend/src/pages/TeamsPage.tsx`, `frontend/src/pages/containers/ResourceUsagePanel.tsx`, `frontend/src/pages/containers/resource-usage-panel.css`, `frontend/e2e/teams.spec.ts`

**Interfaces:**
- Consumes: `GET/PATCH /api/projects/{id}/compute-quota`.
- Produces: `ProjectComputeQuota`, `getProjectComputeQuota`, `updateProjectComputeQuota`; owner-only "Compute limits" form; quota bars in `ResourceUsagePanel`.

- [ ] **Step 1: Add API functions** to `frontend/src/api/projects.ts`:

```ts
export interface ProjectComputeQuota {
  max_running_containers: number | null
  max_cpu_millicores: number | null
  max_memory_bytes: number | null
  max_deploys_per_hour: number | null
  used_running_containers: number
  used_cpu_millicores: number
  used_memory_bytes: number
  used_deploys_per_hour: number
  platform_ceiling: Record<string, number | null>
}

export async function getProjectComputeQuota(projectId: string): Promise<ProjectComputeQuota> {
  return apiGet<ProjectComputeQuota>(`/projects/${projectId}/compute-quota`)
}

export async function updateProjectComputeQuota(
  projectId: string,
  update: Partial<Pick<ProjectComputeQuota, 'max_running_containers' | 'max_cpu_millicores' | 'max_memory_bytes' | 'max_deploys_per_hour'>>,
): Promise<ProjectComputeQuota> {
  return apiPatch<ProjectComputeQuota>(`/projects/${projectId}/compute-quota`, update)
}
```

Re-export the type and both functions from `frontend/src/api/client.ts` alongside the storage-quota helpers.

- [ ] **Step 2: Extend the state hook and `TeamDetail`** — first extend `frontend/src/pages/teams/useTeamManagement.ts` with `computeQuota` state, a `getProjectComputeQuota` fetch and an `updateProjectComputeQuota` save mirroring the existing storage flow (`getProjectStorageQuota` / `updateProjectStorageQuota`), and expose the new state and save function through `TeamsPage` to `TeamDetail`. Then extend `frontend/src/pages/teams/TeamDetail.tsx` with a Compute section mirroring the Storage section at lines 101-175: render `used/total` bars for containers, CPU (millicores) and memory (GiB) using the existing bar markup and `role="status"` semantics; when `isSelectedOwner`, render a compact form with three numeric inputs (containers, CPU millicores, memory GiB) and a Save button that calls `updateProjectComputeQuota` with null-on-empty, shows a success `role="status"` message, and a `role="alert"` error from `formatApiError`.

- [ ] **Step 3: Extend `frontend/src/pages/containers/ResourceUsagePanel.tsx`** so each project card also shows a compute usage row (`containers`, `CPU`, `memory`) when a compute limit exists. Add any new selectors to `resource-usage-panel.css` using existing design tokens only — no raw hex.

- [ ] **Step 4: Add an E2E check** to `frontend/e2e/teams.spec.ts` using the `instructorPage` fixture: open a team, assert the Compute section shows "Compute limits" for the owner, save a container limit of `5`, and assert the success banner. Keep the existing storage tests unchanged.

- [ ] **Step 5: Verify**

Run:
```bash
cd frontend
npm run typecheck && npm run lint && npm run build
npm run test:e2e -- e2e/teams.spec.ts
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/projects.ts frontend/src/api/client.ts frontend/src/pages/teams/useTeamManagement.ts frontend/src/pages/teams/TeamDetail.tsx frontend/src/pages/TeamsPage.tsx frontend/src/pages/containers/ResourceUsagePanel.tsx frontend/src/pages/containers/resource-usage-panel.css frontend/e2e/teams.spec.ts
git commit -m "feat(ui): add compute quota owner controls and usage panel"
```

---

### Task 6: F09 showback backend and CSV export

**Files:**
- Modify: `backend/app/api/schemas.py`, `backend/app/api/routes/metrics.py`
- Test: `backend/tests/test_showback_api.py`

**Interfaces:**
- Consumes: `ContainerMetric`, `METRICS_INTERVAL_SECONDS`, `team_storage_usage`, `list_accessible_project_ids`, `Project.organization_id`.
- Produces: `GET /api/metrics/showback` → `ShowbackSummary`; `GET /api/metrics/showback/export?month=YYYY-MM` → CSV.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_showback_api.py`

```python
def test_showback_is_team_scoped_and_reports_resource_time(api_client):
    response = api_client.get("/api/metrics/showback")
    assert response.status_code == 200
    body = response.json()
    assert "teams" in body
    for team in body["teams"]:
        assert set(team) >= {"team_name", "cpu_seconds", "memory_gib_hours", "storage_gib_days"}
        assert team["cost_currency"] is None


def test_showback_is_401_for_anonymous(anonymous_client) -> None:
    assert anonymous_client.get("/api/metrics/showback").status_code == 401


def test_csv_export_has_expected_header(api_client) -> None:
    response = api_client.get("/api/metrics/showback/export?month=2026-11")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0] == "team,cpu_seconds,memory_gib_hours,storage_gib_days"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_showback_api.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Add schemas** to `backend/app/api/schemas.py` after `UsageSummary`:

```python
class TeamShowback(BaseModel):
    team_name: str
    cpu_seconds: float
    memory_gib_hours: float
    storage_gib_days: float
    cost_currency: None = None


class ShowbackSummary(BaseModel):
    month: str
    teams: list[TeamShowback]
```

- [ ] **Step 4: Implement the routes** in `backend/app/api/routes/metrics.py`:

```python
from app.core.monitoring.metrics_collector import METRICS_INTERVAL_SECONDS
from app.api.schemas import ShowbackSummary, TeamShowback
from fastapi.responses import StreamingResponse
import csv
import io


async def _resource_time(session, container_ids: list[str], days: int) -> tuple[float, float]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    cpu_seconds = 0.0
    memory_gib_seconds = 0.0
    if container_ids:
        rows = (await session.execute(
            select(ContainerMetric).where(
                ContainerMetric.timestamp >= since,
                ContainerMetric.container_id.in_(container_ids),
            )
        )).scalars().all()
        for row in rows:
            cpu_seconds += (row.cpu_percent / 100) * METRICS_INTERVAL_SECONDS
            memory_gib_seconds += (row.memory_usage_bytes / 1024**3) * METRICS_INTERVAL_SECONDS
    return cpu_seconds, memory_gib_seconds / 3600


@router.get("/showback", response_model=ShowbackSummary)
async def get_showback(current_user=Depends(get_current_user), session=Depends(get_db), orchestrator=Depends(get_orchestrator)):
    if current_user.role == UserRole.ADMIN:
        project_ids = set((await session.execute(select(Project.id))).scalars().all())
        containers = await orchestrator.list()
    else:
        project_ids = await list_accessible_project_ids(session, current_user.id)
        containers = await orchestrator.list(project_ids=project_ids, user_id=current_user.id)
    ids_by_project: dict[uuid.UUID, list[str]] = {}
    for info in containers:
        raw_project_id = info.labels.get(VELA_PROJECT_LABEL)
        try:
            ids_by_project.setdefault(uuid.UUID(raw_project_id), []).append(info.id)
        except (TypeError, ValueError):
            continue
    projects = (await session.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()
    teams: list[TeamShowback] = []
    for project in projects:
        cpu_seconds, memory_gib_hours = await _resource_time(
            session, ids_by_project.get(project.id, []), 30,
        )
        disk_bytes, uploads_bytes = await team_storage_usage(session, orchestrator, project.id)
        storage_gib = (disk_bytes + uploads_bytes) / 1024**3
        teams.append(TeamShowback(
            team_name=project.name,
            cpu_seconds=cpu_seconds,
            memory_gib_hours=memory_gib_hours,
            # ponytail: current storage × 30 days; no storage time series exists yet.
            storage_gib_days=storage_gib * 30,
        ))
    since = datetime.now(timezone.utc) - timedelta(days=30)
    return ShowbackSummary(month=since.strftime("%Y-%m"), teams=teams)


@router.get("/showback/export")
async def export_showback(month: str, current_user=Depends(get_current_user), session=Depends(get_db), orchestrator=Depends(get_orchestrator)):
    summary = await get_showback(current_user, session, orchestrator)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["team", "cpu_seconds", "memory_gib_hours", "storage_gib_days"])
    for team in summary.teams:
        writer.writerow([team.team_name, team.cpu_seconds, team.memory_gib_hours, team.storage_gib_days])
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="vela-showback-{month}.csv"'})
```

Use the module's existing `Annotated[...]` dependency style and add `orchestrator` / `session` parameters to the export handler explicitly rather than forwarding them positionally if the router requires it. Scoping mirrors `get_usage` (metrics.py:144-147): one `orchestrator.list(project_ids=..., user_id=current_user.id)` call, containers grouped by `VELA_PROJECT_LABEL`, then per-team `ContainerMetric.container_id.in_(ids)` — never an unscoped `ContainerMetric` query; admins widen to all projects with an unfiltered list.

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_showback_api.py tests/test_metrics_api.py -q && ruff check .`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes/metrics.py backend/tests/test_showback_api.py
git commit -m "feat(metrics): add team showback and CSV export"
```

---

### Task 7: F09 frontend showback dashboard

**Files:**
- Create: `frontend/src/api/showback.ts`, `frontend/src/pages/ShowbackPage.tsx`, `frontend/src/pages/showback.css`
- Modify: `frontend/src/api/client.ts`, `frontend/src/App.tsx` (or the router module used there), `frontend/e2e/dashboard.spec.ts`

**Interfaces:**
- Consumes: `GET /api/metrics/showback` and `/showback/export`.
- Produces: a `[ SHOWBACK ]` page with a per-team table, a `MetricChart` of CPU-seconds, and a CSV download button.

- [ ] **Step 1: Create `frontend/src/api/showback.ts`**

```ts
import { apiGet } from './core'

export interface TeamShowback {
  team_name: string
  cpu_seconds: number
  memory_gib_hours: number
  storage_gib_days: number
  cost_currency: null
}

export interface ShowbackSummary {
  month: string
  teams: TeamShowback[]
}

export const getShowback = (): Promise<ShowbackSummary> => apiGet<ShowbackSummary>('/metrics/showback')

export async function exportShowbackCsv(month: string): Promise<void> {
  const response = await fetch(`/api/metrics/showback/export?month=${encodeURIComponent(month)}`, {
    headers: { Authorization: `Bearer ${localStorage.getItem('vela.access_token') ?? ''}` },
  })
  if (!response.ok) throw new Error('Could not export showback report')
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `vela-showback-${month}.csv`
  link.click()
  URL.revokeObjectURL(url)
}
```

Re-export from `frontend/src/api/client.ts`.

- [ ] **Step 2: Create `frontend/src/pages/ShowbackPage.tsx`**

Follow `ResourceDashboardPage.tsx`: page title `[ SHOWBACK ]`, loading `<Skeleton>` placeholders, `role="alert"` error banner using `formatApiError`, empty state when `teams` is empty, a `formatTable`-style semantic `<table>` with team / CPU-seconds / memory GiB-h / storage GiB-days, a `MetricChart` for CPU-seconds by team, and a `role="status"` confirmation after CSV download. Import `./showback.css`; keep all styling in that file using tokens only.

- [ ] **Step 3: Register the route in `frontend/src/App.tsx`** at `/showback`, using the same protected-route wrapper as `ResourceDashboardPage`.

- [ ] **Step 4: Add an E2E assertion** in `frontend/e2e/dashboard.spec.ts` that navigates to `/showback` and expects the `[ SHOWBACK ]` title and the table header `Team`.

- [ ] **Step 5: Verify**

Run:
```bash
cd frontend
npm run typecheck && npm run lint && npm run build
npm run test:e2e -- e2e/dashboard.spec.ts
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/showback.ts frontend/src/api/client.ts frontend/src/pages/ShowbackPage.tsx frontend/src/pages/showback.css frontend/src/App.tsx frontend/e2e/dashboard.spec.ts
git commit -m "feat(ui): add per-team showback dashboard"
```

---

### Task 8: F18 — real RPS scaling and signal status

**Files:**
- Modify: `backend/app/core/scaling/scaling_engine.py`, `backend/app/core/models.py`, `backend/app/api/routes/scaling.py`, `backend/app/core/traffic/traffic_router.py` (only if needed for type check), `frontend/src/api/scaling.ts`, `frontend/src/pages/containers/ContainersRunScalingFields.tsx`, `backend/tests/test_scaling_engine.py`
- Create: `backend/tests/test_scaling_api.py` (new spec covering GET list/one, PUT, and `signal_unavailable` on responses)

**Interfaces:**
- Consumes: `get_edge_request_rates` from Task 1; `ScalingMetric.REQUESTS_PER_SECOND`; injected `TrafficRouter`.
- Produces: RPS branch in `_measure_metric`; computed `signal_unavailable: bool` on `ScalingPolicyInfo` and in the scaling API responses.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_scaling_engine.py`

```python
import asyncio
from types import SimpleNamespace

from app.core.enums import ScalingMetric
from app.core.monitoring import edge_requests
from app.core.scaling.scaling_engine import _measure_metric
from app.core.traffic.traffic_router import NoopTrafficRouter


class _Stats:
    cpu_percent = 42.0


class _Orchestrator:
    async def get_stats(self, name: str) -> _Stats:
        return _Stats()


class _EdgeRouter:
    async def get_route(self, name: str) -> object:
        return SimpleNamespace(host="web.example")


def test_noop_router_keeps_cpu_proxy() -> None:
    result = asyncio.run(_measure_metric(
        _Orchestrator(), "web", ScalingMetric.REQUESTS_PER_SECOND, NoopTrafficRouter(),
    ))
    assert result == 42.0


def test_rps_uses_edge_counter(monkeypatch) -> None:
    monkeypatch.setattr(
        edge_requests, "get_edge_request_rates",
        lambda: edge_requests.EdgeRequestRates({"web.example": 12.0}, True),
    )
    result = asyncio.run(_measure_metric(
        _Orchestrator(), "web", ScalingMetric.REQUESTS_PER_SECOND, _EdgeRouter(),
    ))
    assert result == 12.0


def test_rps_fails_closed_when_signal_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        edge_requests, "get_edge_request_rates",
        lambda: edge_requests.EdgeRequestRates({}, False),
    )
    result = asyncio.run(_measure_metric(
        _Orchestrator(), "web", ScalingMetric.REQUESTS_PER_SECOND, _EdgeRouter(),
    ))
    assert result is None
```

Also create `backend/tests/test_scaling_api.py` — the file does not exist yet, so create rather than modify. Write a new spec covering GET list, GET one, PUT and the `signal_unavailable` field on the responses, using the `api_client` fixture and the seeding pattern from `backend/tests/test_replica_config.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_scaling_engine.py -q`
Expected: FAIL — signature mismatch (new `router` parameter missing).

- [ ] **Step 3: Change `_measure_metric`** in `backend/app/core/scaling/scaling_engine.py`:

```python
async def _measure_metric(
    orchestrator: ContainerOrchestrator,
    container_name: str,
    metric: ScalingMetric,
    traffic_router: TrafficRouter,
) -> float | None:
    if metric is ScalingMetric.REQUESTS_PER_SECOND and not isinstance(traffic_router, NoopTrafficRouter):
        signal = edge_requests.get_edge_request_rates()
        if not signal.available:
            return None
        try:
            route = await traffic_router.get_route(container_name)
        except RouteNotFoundError:
            return None
        if route.host not in signal.rates_by_host:
            return None
        return signal.rates_by_host[route.host]
    stats = await _stats_or_none(orchestrator, container_name)
    if stats is None:
        return None
    # ponytail: noop router has no request signal; CPU is an explicit, documented proxy.
    return float(stats.cpu_percent)
```

Keep the existing try/except orchestrator error handling in a new `_stats_or_none` helper. Update the single call in `_evaluate_policy` to pass `traffic_router`. Import the module (`from app.core.monitoring import edge_requests`) and call through it — `edge_requests.get_edge_request_rates()` — so the Step 1 monkeypatch of `edge_requests.get_edge_request_rates` is visible to the engine; `RouteNotFoundError` is already imported in the module, and `traffic_router.get_route` raises it for unrouted containers (never returns `None`), so catch it and return `None` instead of testing `route is not None`.

- [ ] **Step 4: Add computed signal status** to `ScalingPolicyInfo` in `backend/app/core/models.py`:

```python
    signal_unavailable: bool = False
```

In `backend/app/api/routes/scaling.py`, set it on every returned `ScalingPolicyInfo` by wrapping the values returned by `list_policies_for_container_names`, `get_policy` and `upsert_policy` (those helpers live in `app/core/scaling/policy_repository.py`; the route module only imports them):

```python
def _with_signal_status(info: ScalingPolicyInfo) -> ScalingPolicyInfo:
    if info.metric is ScalingMetric.REQUESTS_PER_SECOND and not isinstance(get_traffic_router(), NoopTrafficRouter):
        info.signal_unavailable = not get_edge_request_rates().available
    return info
```

Apply `_with_signal_status` in the GET list, GET one and PUT handlers.

- [ ] **Step 5: Frontend status surfacing** — add `signal_unavailable: boolean` to `frontend/src/api/scaling.ts` `ScalingPolicyInfo`; in `frontend/src/pages/containers/ContainersRunScalingFields.tsx`, render a `role="status"` line "RPS signal unavailable — scaling paused" when the selected metric is `requests_per_second` and the field is true. No new CSS file needed if an existing class fits; otherwise add to the page's existing CSS.

- [ ] **Step 6: Run tests**

Run:
```bash
cd backend
python -m pytest tests/test_scaling_engine.py tests/test_scaling_api.py -q
ruff check . && mypy app/ tests/
cd ../frontend && npm run typecheck && npm run lint
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/scaling/scaling_engine.py backend/app/core/models.py backend/app/api/routes/scaling.py backend/tests/test_scaling_engine.py backend/tests/test_scaling_api.py frontend/src/api/scaling.ts frontend/src/pages/containers/ContainersRunScalingFields.tsx
git commit -m "feat(scaling): drive RPS policies from the edge counter"
```

---

## Self-review (done at plan authoring)

- **Spec coverage:** F02 → Tasks 1–2; F03 → Tasks 3–5; F09 → Tasks 6–7; F18 → Task 8. All locked decisions are represented, including the 409 status, the admin ceiling, the replica-deploy admission path, fail-closed RPS, and the `noop` CPU proxy.
- **Placeholder scan:** no TBD/TODO. Steps 6 of Task 3 and 4 of Task 6 contain minor "replace this import/style with the neighbouring one" instructions because the exact alias depends on the surrounding module; all behaviour and data shapes are specified.
- **Type consistency:** `EdgeRequestRates` from Task 1 is used unchanged by Tasks 2 and 8; `enforce_team_compute_capacity` from Task 3 is used by Task 4; `get_edge_request_rates` is the single shared feed; `signal_unavailable` is added to backend schema and frontend type in the same task.
