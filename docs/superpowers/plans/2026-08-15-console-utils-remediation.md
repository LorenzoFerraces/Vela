# Console Utils Remediation Plan

- **Date:** 2026-08-15
- **Status:** Ready for execution
- **Required skill:** superpowers:executing-plans
- **Depends on:** review findings for branch `f/console-utils` (see "Findings" below)

## Goal

Repair branch `f/console-utils` (audit log, terminal access, log aggregation) so the backend
imports, the frontend builds, migrations are single-headed, and every plan-level requirement
(ownership checks, exec WS auth, audit flush semantics, log dedup) actually holds — then make
the whole suite (backend pytest, `npm run build`, Playwright E2E) green.

Root causes: the feature-branch merge commit (`c589b60`, merging main `5ae50c1`) was botched —
conflict markers committed into `index.css`, JSX spliced in `App.tsx`, two `include_router`
calls nested in `app.py`, an unclosed tuple in `models.py`, and two divergent `0014_*` migration
heads. On top of that the review found one security hole (logs API has no ownership check), a
frontend infinite-refetch bug, and a log-collector data-loss cursor. This plan fixes the merge
damage first (nothing else is testable until then), then the functional defects.

## Findings (severity → what this plan does)

| Id | Sev | Where | Issue | Task |
|----|-----|-------|-------|------|
| C1 | Critical | `backend/app/api/app.py:188-195` | `include_router(stacks.router, ...)` nested inside the `include_router(audit.router, ...)` call → `SyntaxError: positional argument follows keyword argument`. Backend unimportable; pytest cannot collect; uvicorn cannot start. | T1 |
| C2 | Critical | `backend/app/db/models.py:484` | `__table_args__ = (` never closed → `SyntaxError: '(' was never closed`; every `app.db.models` import fails. | T1 |
| C3 | Critical | `frontend/src/App.tsx:80-121` | Merge mangled JSX: unclosed `Routes`/`Route`, `/stacks*` routes spliced into the `/logs` route. `npm run build` fails with 10 tsc errors (TS17008/1382/17002/1381). | T2 |
| C4 | Critical | `frontend/src/index.css` | Committed merge-conflict markers at 2733, 2756, 2799, 2880, 2922, 2935, 3233 (markers fused into CSS rules, e.g. `=======.stacks-builder__checkbox {`). Vite build breaks. | T2 |
| C5 | Critical | `backend/alembic/versions/` | Multiple heads: both `0014_audit_log` and `0014_stacks` point at `0013_scaling_stabilization`; heads = {`0016_build_override`, `0016_container_logs`}. `alembic upgrade head` fails; a production DB at main's head would not get the new tables. | T3 |
| H1 | High | `backend/app/api/routes/logs.py:24-37,86-95` | `GET /api/logs` + `/api/logs/export` only have `get_current_user`; free-form `container_id`, no ownership check → any authenticated user can read/export any container's logs. `require_container_access` already exists at `backend/app/core/projects/access.py:58`. | T5 |
| H2 | High | `frontend/src/pages/AuditLogPage.tsx:30-51` | Infinite refetch loop: `reqSeq` is state in the `useCallback` deps AND set inside the effect; the guard `seq === reqSeq` compares against a stale-closure value and is always false → entries never render + unbounded requests. | T10 |
| H3 | High | `backend/app/core/logging/collector.py` | `_last_seen` content cursor silently loses lines: >200 lines per interval → window slides past uncollected lines; a repeated last line (heartbeat) → that line is never captured again; process restart replays the tail-200. | T7 |
| H4 | High | `backend/app/api/app.py:64-67` | `LogCollector(get_orchestrator())` in lifespan is unguarded (the scaling loop just above IS guarded). If Docker is unavailable and `VELA_FAKE_ORCHESTRATOR` is off, app boot fails. | T7 |
| H5 | High | collector + `backend/tests/conftest.py` | Collector starts in every TestClient test (enabled by default), calls `get_orchestrator()` dep directly (bypasses `dependency_overrides`) and uses the env-var `get_session_factory()` engine — a separate in-memory SQLite with no tables → `no such table: container_logs` tracebacks in every test. | T4/T7 |
| M1 | Medium | `collector.py:27-28` | `_DOCKER_TS_RE` never matches real `docker logs` output → timestamp = collection time (one per batch, in-batch order arbitrary), `source` always `STDOUT` (source filter is dead). Dead regex. | T7 |
| M2 | Medium | `docker_orchestrator.py:790-801` | Reader thread: `Queue(maxsize=64)` + `run_coroutine_threadsafe(queue.put(chunk), loop).result(timeout=30)`. Under >30s backpressure the sentinel put times out → `exec_runtime.close()` skipped → socket + semaphore slot leak. | T8 |
| M3 | Medium | `docker_orchestrator.py` / `containers.py` exec path | Blocking Docker HTTP on the event loop: exec_create/exec_start per session, `stdin.write` per keystroke, `exec_resize` per resize. Also: logger constructed between imports at `docker_orchestrator.py:20`. | T8/T12 |
| M4 | Medium | `containers.py:1143` | `async with _exec_semaphore` has no acquire timeout; one blackholed connection holds a slot forever; 20 dropped sessions → all terminals locked out. | T8 |
| M5 | Medium | `containers.py:1119` | `await websocket.accept()` happens BEFORE token validation; JWT rides in the query string (`?access_token=`). | T8 |
| M6 | Medium | `containers.py` exec path | Exec start failure (e.g. image without `sh`) is only logged; user sees a generic closed socket. | T8 |
| M7 | Medium | audit coverage | No `container.exec` audit event; every other write action is audited. | T6 |
| M8 | Medium | `backend/app/core/audit/service.py:54-69` | Implementation does flush + `commit()` (line 64) + `rollback()` in the except path (line 69). Plan (audit-log) specified flush only. The `rollback()` rolls back pending work on the request session — a landmine. | T6 |
| M9 | Medium | `backend/app/api/routes/audit.py:32` | Self-scoped only (`user_id=current_user.id`); the plan's admin view + `user_id` filter param were not implemented. Deviation is SAFER; kept as a product decision. | Decision (no task) |
| M10 | Medium | `0016_container_logs.py` | Migration creates GIN `ix_container_logs_fts` (PG-only) but the ORM metadata doesn't declare it → `alembic check` / autogenerate drift. | T1 |
| M11 | Medium | `frontend/package.json` | `xterm@5.3.0` / `xterm-addon-fit@0.8.0` are deprecated legacy packages (successors `@xterm/*`). No action now — migration is a separate, larger task; noted. | Decision |
| M12 | Medium | `README.md` | New env vars `VELA_LOG_COLLECTOR_ENABLED`, `VELA_LOG_POLL_INTERVAL_S`, `VELA_LOG_MAX_LINES_PER_POLL` (+ `VELA_EXEC_MAX_SESSION_SECONDS` added by T8) undocumented. | T12 |
| L1 | Low | `logs.py:45,47` | `LogLevel(level)` / `LogSource(source)` raise `ValueError` on bad query param → 500 instead of 422. | T5 |
| L2 | Low | `logs.py:106-148` | Export materializes up to 50k rows in memory. Accepted ceiling (documented), no task. | Decision |
| L3 | Low | `ContainerTerminal.tsx:36-52` | React StrictMode double-effect creates/duplicates the WS + term momentarily (dev/e2e). Add guard. | T10 |
| L4 | Low | `frontend/e2e/terminal.spec.ts` | Only asserts pane visibility, self-skips when no container; plan required typing a command and verifying output. | T11 |
| L5 | Low | `conftest.py` | Persistent single session across requests (required for in-memory SQLite visibility). Keep. | Decision |
| L6 | Low | audit | `details` stores field names only (users.py:43), not values — less forensically useful, no secrets leaked. Keep. | Decision |
| L7 | Low | audit | Failed actions are not audited (success-only, as planned). Keep. | Decision |
| L8 | Low | `containers.py` | Module-level `_exec_semaphore` lazily bound to loop. Keep, document. | Decision |
| L10 | Low | `containers.py:1184-1192` | Resize JSON unvalidated; JSON-shaped shell input can be swallowed as a control message. Validate. | T8 |
| N1-N10 | Nitpick | various | Dead code (`create_log_collector`, `dataclass` import, unused `done`, `if lines:`), `params as any` ×3, `instanceof ArrayBuffer` (client.ts:682), css reformat churn, logger placement, test imports, slow WS tests, free-text container id. | T12/T10 |

## Accepted deviations (do NOT "fix")

- **Self-scoped audit (M9):** self-only view is strictly safer than the plan's admin view. Ship as-is; admin audit view is a future product decision.
- **Log API filters stay `LIKE` (no trigram ops in ORM queries):** the 0016 migration keeps the GIN trgm index for future use; ORM metadata gets the index declared (T1) so autogenerate stops churning.
- **WS auth close code 1008:** spec text in the terminal plan says 1000; 1008 (policy violation) is the correct code and matches the existing log WS.
- **`stream_exec` tuple return:** keep; the plan's snippet was wrong (its "close early" bug is avoided by the current sentinel design).
- **`conftest.py` persistent session (L5):** keep — required for in-memory SQLite.
- **Timestamps of collected log lines:** collection time, not event time. The Docker SDK returns unstructured text with no per-line timestamps; parsing `docker logs` formats is format-fragile. Documented; `since=cursor` (container uptime) is the ordering guarantee instead.
- **`xterm` deprecated packages (M11):** functional; migration to `@xterm/*` is a separate task.

## File map

Backend (all paths under `backend/`):
- `app/api/app.py` — T1 (router nesting), T7 (guard collector wiring)
- `app/db/models.py` — T1 (close tuple + trgm index declaration)
- `alembic/versions/0017_merge_console_utils_heads.py` — T3 (new)
- `app/api/routes/logs.py` — T5 (ownership, enum validation, required container_id, export `q`)
- `app/api/routes/containers.py` — T6 (`container.exec` audit), T8 (exec WS hardening)
- `app/core/audit/service.py` — T6 (flush-only)
- `app/core/logging/collector.py` — T4 (injectable factory), T7 (cursor rewrite)
- `app/core/containers/orchestrator.py` — T7 (`since` on abstract `logs`)
- `app/core/containers/docker_orchestrator.py` — T7 (`since`), T8 (reader/leak), T12 (logger placement)
- `app/core/containers/fake_orchestrator.py` — T7 (incrementing log lines)
- `tests/conftest.py` — T4 (disable collector in pytest)
- `tests/test_log_api.py` — T5 (ownership/422/404 tests)
- `tests/test_log_collector.py` — T7 (cursor unit tests)
- `tests/test_api_integration.py:529,572` — T7 (fake-lines assertions)
- `tests/test_exec_ws.py` (or the existing exec WS test file — locate with `rg "exec/ws" tests`) — T8
- `README.md` — T12 (env vars)

Frontend (all paths under `frontend/`):
- `src/App.tsx` — T2
- `src/index.css` — T2
- `src/pages/LogsPage.tsx` — T5 (required container guard, prefill, typed params)
- `src/pages/AuditLogPage.tsx` — T10 (loop fix, typing)
- `src/api/client.ts` — T5 (`LogQueryParams` drops `container_name`), T10 (`instanceof` → cast)
- `src/components/workloads/ContainerTerminal.tsx` — T10 (disposed guard)
- `e2e/logs.spec.ts` — T5 (404 expectation)
- `e2e/terminal.spec.ts` — T11 (type + assert output)

## Environment

- Repo: `F:\lolo\fac\Vela`; branch `f/console-utils`.
- PowerShell 5.1. Backend venv: `F:\lolo\fac\Vela\.venv\Scripts\python.exe`; run backend commands with `workdir = F:\lolo\fac\Vela\backend`.
- Frontend: `cd F:\lolo\fac\Vela\frontend` (or `workdir`), commands via `npm run ...`.
- Commit after each task. Message style: `fix(console-utils): <short>` / `test(console-utils): <short>`.
- **Verify after EVERY task that changes code:** the commands listed in that task, then before finishing the whole plan: full gate in T12.

---

### Task 1 — Unblock backend imports (C1, C2, M10)

**Step 1.1** In `backend/app/api/app.py`, replace the nested block (lines 188-195):

```python
app.include_router(
    audit.router,
    prefix="/api",
    tags=["audit"],
    app.include_router(stacks.router, prefix="/api", tags=["stacks"]),
)
```

with two separate statements:

```python
app.include_router(audit.router, prefix="/api", tags=["audit"])
app.include_router(stacks.router, prefix="/api", tags=["stacks"])
```

**Step 1.2** In `backend/app/db/models.py`, the `ContainerLog.__table_args__` (starts line 484) is missing its closing element/tuple. Rewrite the tail of the class so it ends:

```python
    __table_args__ = (
        CheckConstraint("level >= 0 AND level <= 3", name="ck_container_log_level"),
        CheckConstraint(
            "source IN ('STDOUT', 'STDERR')", name="ck_container_log_source"
        ),
        Index(
            "ix_container_logs_fts",
            "message",
            postgresql_using="gin",
            postgresql_ops={"message": "gin_trgm_ops"}
        ),
        Index(
            "ix_container_logs_query",
            "container_id",
            "created_at",
            "level",
            "source",
        ),
    )
```

(If the existing block also contains the `UniqueConstraint` / index entries, keep them — add the GIN `Index` and close the tuple. Add `Index` to the sqlalchemy imports at the top of models.py if not already imported.)

**Step 1.3** Verify imports work (collect-only exercises `app.api.app` + `app.db.models` through conftest):

```powershell
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests -q --collect-only
```
Expected: collection succeeds (0 errors). Tests themselves may still fail — that's fine until later tasks.

**Step 1.4** Commit: `fix(console-utils): unblock backend imports (router nesting, models tuple, trgm index)`

---

### Task 2 — Unblock frontend build (C3, C4)

**Step 2.1** In `frontend/src/App.tsx`, replace the mangled JSX at lines 80-121 with a clean route set (component imports already exist at lines 13-17):

```tsx
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
          <Route path="/containers" element={<ContainersPage />} />
          <Route path="/containers/:id" element={<ContainerDetailPage />} />
          <Route path="/images" element={<ImagesPage />} />
          <Route path="/scaling" element={<ScalingPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/audit" element={<AuditLogPage />} />
          <Route path="/stacks" element={<StacksPage />} />
          <Route path="/stacks/new" element={<StacksPage />} />
          <Route path="/stacks/import" element={<StacksPage />} />
          <Route path="/stacks/:id" element={<StacksPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
```
(Match the EXISTING route names/pages in the file — verify each element against current imports before overwriting; the list above is what the pre-merge layout contained. If the pre-merge file (see `git show c589b60^2:frontend/src/App.tsx`) has more routes, restore exactly that set plus `/logs`, `/audit`, `/stacks*`.)

**Step 2.2** Resolve `frontend/src/index.css` via a 3-way union merge (both sides added disjoint blocks; union keeps both, no markers):

```powershell
$base = (git -C F:\lolo\fac\Vela merge-base c589b60^1 c589b60^2).Trim()
git -C F:\lolo\fac\Vela show "${base}:frontend/src/index.css" | Out-File -Encoding utf8 $env:TEMP\opencode\css-base.css
git -C F:\lolo\fac\Vela show "c589b60^2:frontend/src/index.css" | Out-File -Encoding utf8 $env:TEMP\opencode\css-ours.css
git -C F:\lolo\fac\Vela show "c589b60^1:frontend/src/index.css" | Out-File -Encoding utf8 $env:TEMP\opencode\css-theirs.css
git merge-file --union $env:TEMP\opencode\css-ours.css $env:TEMP\opencode\css-base.css $env:TEMP\opencode\css-theirs.css
Copy-Item -LiteralPath $env:TEMP\opencode\css-ours.css F:\lolo\fac\Vela\frontend\src\index.css
```
Then sanity-grep: zero occurrences of `<<<<<<<`, `>>>>>>>`, `=======`; and presence of: `.logs-page`, `.audit-log-page`, `.workloads-terminal`, plus the pre-existing stacks classes (e.g. `.stacks-builder__checkbox`). If the union produced duplicated conflicting rules on the SAME selector, dedupe by hand (keep the one that wins CSS-order; both are valid declarations so this is cosmetic).

**Step 2.3** Verify:

```powershell
npm run build
npm run lint
```
Expected: `tsc -b && vite build` clean, lint clean.

**Step 2.4** Commit: `fix(console-utils): unblock frontend build (App routes, index.css merge)`

---

### Task 3 — Single Alembic head (C5)

**Step 3.1** Create `backend/alembic/versions/0017_merge_console_utils_heads.py`:

```python
"""merge console-utils migration heads

Revision ID: 0017_merge_console_utils
Revises: 0016_build_override, 0016_container_logs
Create Date: 2026-08-15

"""
from alembic import op
import sqlalchemy as sa

revision: str = "0017_merge_console_utils"
down_revision: tuple[str, str] = ("0016_build_override", "0016_container_logs")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```
(Match the revision-style conventions of the neighboring versions — string type imports, `op`/`sa` usage — to `0016_container_logs.py`.)

**Step 3.2** Verify:

```powershell
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m alembic heads
```
Expected: exactly one head — `0017_merge_console_utils (head)`.

```powershell
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m alembic upgrade head --sql
```
Expected: offline migration script renders without error (no DB connection needed; `sync_database_url_for_alembic` handles the driver). If offline mode fails for environmental reasons, fallback: `docker compose -f docker-compose.dev.yml up -d` from repo root, then `alembic upgrade head` against a throwaway database URL, and confirm `audit_log` + `container_logs` tables exist.

**Step 3.3** Commit: `fix(console-utils): merge alembic heads (0017)`

---

### Task 4 — Make the collector testable (H5)

**Step 4.1** In `backend/app/core/logging/collector.py`, make the session factory injectable:

- `def __init__(self, orchestrator: ContainerOrchestrator, *, session_factory: Callable[[], Any] | None = None) -> None:`
- store `self._session_factory = session_factory or get_session_factory`
- replace the two `get_session_factory()` call sites with `self._session_factory()`.

**Step 4.2** At the very top of `backend/tests/conftest.py` (before any `app.*` import, after the module docstring):

```python
import os

os.environ.setdefault("VELA_LOG_COLLECTOR_ENABLED", "0")
```
(`bootstrap_env` uses `setdefault`, so a pre-set env var wins.)

**Step 4.3** Verify the collector no longer spams/tracebacks in tests:

```powershell
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests -q -x --co 2>&1 | Select-String "error" 
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests/test_log_api.py -q
```
`test_log_api.py` collects and its endpoint tests pass (they don't depend on the collector). If any other test file still emits `no such table: container_logs`, it uses its own `TestClient` without the app lifespan override — report it and apply the same env fix there.

**Step 4.4** Commit: `test(console-utils): disable log collector in pytest, injectable session factory`

---

### Task 5 — Logs API: ownership + validation (H1, L1, H2-adjacent, M1-lite, N2 partial)

**Step 5.1 (test first)** In `backend/tests/test_log_api.py`, add/adjust:

```python
def test_logs_requires_container_id(api_client):
    resp = api_client.get("/api/logs")
    assert resp.status_code == 422


def test_logs_invalid_level_is_422(api_client):
    resp = api_client.get("/api/logs?container_id=cid-1&level=NOT_A_LEVEL")
    assert resp.status_code == 422


def test_foreign_container_logs_are_forbidden(other_user_client):
    resp = other_user_client.get("/api/logs?container_id=cid-1")
    assert resp.status_code == 404


def test_owner_can_query_container_logs(api_client):
    resp = api_client.get(
        "/api/logs?container_id=cid-1&level=INFO&source=STDOUT&limit=5"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 0
    assert "items" in body
```
(Adapt fixture names to what `conftest.py` actually provides — `api_client`, `other_user_client` exist per AGENTS.md. `cid-1` must be a container owned by the `api_client` user in the seeded fixtures; check how other tests obtain a container id — e.g. `POST /api/containers/run` with the fake orchestrator — and do the same instead of hardcoding if no seed provides one.)

Run: `F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests/test_log_api.py -q` — the new tests FAIL (404 test currently 200; 422 tests currently 500/200).

**Step 5.2** Rewrite `query_logs` in `backend/app/api/routes/logs.py`:

```python
router = APIRouter(prefix="/logs", tags=["logs"])


def _require_container_ownership(session: Session, orchestrator: ContainerOrchestrator, user: User, container_id: str) -> None:
    try:
        require_container_access(session, orchestrator, user, container_id, action="read")
    except ContainerNotFoundError:
        raise HTTPException(status_code=404, detail="Container not found.")
    except ProjectAccessDeniedError:
        raise HTTPException(status_code=403, detail="No access to this container.")


@router.get("", response_model=LogListResponse)
async def query_logs(
    container_id: str = Query(..., description="Container id (required)"),
    level: LogLevel | None = Query(None),
    source: LogSource | None = Query(None),
    search: str | None = Query(None, max_length=200),
    container_type: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    order: Literal["asc", "desc"] = Query("desc"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: SessionDep,
    current_user: CurrentUser,
    orchestrator: OrchestratorDep,
) -> LogListResponse:
    _require_container_ownership(session, orchestrator, current_user, container_id)
    ...
```
- Drop the `container_name` parameter entirely (it was an ownership hole — name is not a unique/owned identifier).
- `level`/`source` become `Query(None)`-typed enum params → FastAPI returns 422 on garbage (fixes L1). Keep the `entries_query` construction unchanged (the `if order...` precedence bug from the plan's snippet is NOT present — do not "fix" what isn't broken).
- `export_logs`: same `container_id: str = Query(...)`, same ownership guard (action="read"), plus add `search: str | None = Query(None, max_length=200)` (the frontend already sends `q`… check `exportLogs` in `client.ts` — it sends the same params object; name the query param `q` to match what the frontend sends — verify exact key in `client.ts` around line 1460 before finalizing).

**Step 5.3** Frontend `src/api/client.ts`: remove `container_name?: string;` from `LogQueryParams` (line ~1434). In `src/pages/LogsPage.tsx`:
- Container id becomes required: when empty, do NOT fetch (the current effect fetches all-logs — that endpoint shape no longer exists), show an empty-state card "Select a container to view logs" (skeleton → empty state swap, no "Loading…" text).
- Keep the free-text input; prefill from `?container_id=` query param when present (the containers page/detail should deep-link `#/logs?container_id=...` if a "View logs" affordance exists — if it doesn't, add one on the container detail row that navigates there).
- Replace `params as any` (lines ~35, ~58) with a properly typed `buildLogQueryParams(...)` returning `LogQueryParams`.

**Step 5.4** Update `frontend/e2e/logs.spec.ts` test 2: the bogus-container case must now expect the 404 banner (`Container not found.`), not `No logs found`.

**Step 5.5** Verify:

```powershell
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests/test_log_api.py tests/test_api_integration.py -q
cd F:\lolo\fac\Vela\frontend; npm run build; npm run lint
```

**Step 5.6** Commit: `fix(console-utils): logs API ownership + validation`

---

### Task 6 — Audit: flush-only + `container.exec` (M8, M7)

**Step 6.1 (test first)** In the audit integration tests (whichever file covers container actions — `rg "container.stop" backend/tests`), add an exec case and an assertion that a failed request does NOT commit unrelated pending writes (keep it simple: just assert the `container.exec` row appears after an exec WS session). Run it — it fails (no `container.exec` emission).

**Step 6.2** In `backend/app/core/audit/service.py` (`emit_audit_log` body, lines ~54-69): delete `await session.rollback()` (line 69) and delete `await session.commit()` (line 64) — keep only `await session.flush()`. The function must not commit or roll back the request session; it flushes so the caller's `commit()` persists the audit row, and on failure it logs + re-raises (the request's own error handling rolls back). Confirm the `except` path: log + `raise`.

**Step 6.3** In the exec WS route (`backend/app/api/routes/containers.py`, the `/exec/ws` handler): after the access check passes and before (or after — must be inside the `async with` session) the stream begins, emit:

```python
emit_audit_log(
    session,
    user_id=current_user.id,
    action="container.exec",
    container_id=container_id,
    details=None,
)
```
(match the import/call signature of the other emission sites at containers.py:621 etc. — they call `emit_audit_log(...); await session.commit()` right after; mirror that exact pattern.)

**Step 6.4** Verify: backend test suite green for audit + container routes:

```powershell
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests -q -k "audit or exec"
```

**Step 6.5** Commit: `fix(console-utils): audit flush-only + container.exec event`

---

### Task 7 — Log collector: real dedup, no data loss (H3, H4, H5, M1, fake logs)

**Step 7.1 (test first)** Rewrite `backend/tests/test_log_collector.py` with a duck-typed orchestrator (the collector only calls `.list()` and `.logs()`):

```python
class StubOrchestrator:
    def __init__(self):
        self.lines: dict[str, list[str]] = {}
        self.log_calls: list[tuple[str, int | None, int | None]] = []

    def list(self):
        return [(cid, "demo", "running") for cid in self.lines]

    def logs(self, container_id, *, tail: int = 100, since: int | None = None):
        lines = self.lines.get(container_id, [])
        self.log_calls.append((container_id, tail, since))
        return "\n".join(lines) + "\n" if lines else ""
```
(Note: `list()` return shape must match what the collector actually unpacks — check the current collector's handling of `list()` results and mirror it exactly.)

Tests (run a collector with `poll_interval=0`, `max_lines_per_poll=50`, an in-memory `session_factory` built in-test the same way conftest does):
1. `test_first_poll_seeds_without_insert` — 5 lines → `poll_once()` → 0 rows, 2nd `poll_once()` with new line → 1 row (the new one only).
2. `test_overlap_lines_are_deduplicated` — 3 lines overlap between poll 1 and poll 2 window → only genuinely new lines insert.
3. `test_repeated_last_line_is_captured` — line `same\nsame\nsame ...` (repeated heartbeat) growing window → each new occurrence inserts once.
4. `test_gap_larger_than_window_inserts_everything` — window slides fully past uncollected lines (old >200-line loss case) → with `since` support the orchestrator returns only post-cursor lines; all insert, none lost.
5. `test_since_cursor_is_passed` — after first poll, `log_calls[1][2]` (since) is not None and > first cursor.
6. `test_disabled_does_nothing` — `enabled=False` → zero DB rows, no `logs()` calls.

Run: `F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests/test_log_collector.py -q` → fails (new signature + behavior).

**Step 7.2** Widen the `logs()` contract:
- `app/core/containers/orchestrator.py:72` abstract: `def logs(self, container_id: str, *, tail: int = 100, since: int | None = None) -> str:` (docstring: `since` = container uptime seconds, Docker "since" cursor.)
- `docker_orchestrator.py:672-682`: `container.logs(tail=tail, since=since, stdout=True, stderr=True)` (SDK passes unknown kwargs through; `since` is a real Docker log option).
- `fake_orchestrator.py` (around :260-273): stop returning a single static `log line\n`. Give each container an incrementing line list — on `logs()`, if empty for that container append `f"log line {n}"` for a fresh counter (or expose a `fake.add_log_line(container_id, line)` helper used by tests), then return the last `tail` lines joined with `"\n"`. Keep honoring `tail`.

**Step 7.3** Rewrite the collection loop in `collector.py` (replace `_last_seen` content-cursor block, lines ~90-145; delete `_DOCKER_TS_RE` and its use; keep `detect_source`/`infer_level`):

Per-container state: `_seen: dict[str, deque[str]]` (deque with `maxlen = max_lines_per_poll * 2`), `_cursor: dict[str, int]` (seconds since container start, from `list()` uptime), `_last_poll_at: dict[str, float]`.

```python
def _window_since(self, container_id: str) -> int | None:
    last = self._last_poll_at.get(container_id)
    if last is None:
        return None
    started = self._started_at.get(container_id, time.monotonic() - last)
    # since = seconds since container start; clamp to >= 0
    return max(0, int((time.monotonic() - last) ... )) 
```
(`since` semantics: seconds since **container** start for the next poll = previous poll's "now" cursor. Compute as `int(uptime_at_prev_poll + (prev_poll_wall - now_wall))`… keep it simple: store `_since_cursor[container_id] = uptime_at_prev_poll + self.poll_interval * 0` — i.e. the container uptime value captured AT the previous poll. That is the cursor: `logs(since=uptime_at_prev_poll)`. First poll: no cursor → `logs(tail=max_lines_per_poll)` as a seed.)

Per poll per container:
```python
window = self.orchestrator.logs(cid, tail=self.max_lines, since=self._since_cursor.get(cid)) if cid in self._since_cursor else self.orchestrator.logs(cid, tail=self.max_lines)
new_lines = [ln for ln in window.splitlines() if ln]
if cid not in self._seen_deques:           # first sighting: seed only
    self._seed_seen(cid, new_lines)
    self._since_cursor[cid] = uptime_now
    insert 0 rows
    continue
overlapped, fresh = _split_overlap(new_lines, self._seen_deques[cid])
# insert `fresh` rows (timestamp=now, level=infer_level, source=detect_source)
self._push_seen(cid, new_lines)
self._since_cursor[cid] = uptime_now
```

`_split_overlap(window_lines, seen)`:
```python
def _split_overlap(window: list[str], seen: deque[str]) -> tuple[int, list[str]]:
    # ponytail: overlap = longest suffix of `seen` that is a prefix of `window` (line-granular, capped); if container was silent, first lines are all-new
    if not window or not seen:
        return 0, window
    first = window[0]
    if first not in seen:
        return 0, window
    max_k = min(len(window), len(seen), self._OVERLAP_CAP)  # 1024
    for k in range(max_k, 0, -1):
        if list(itertools.islice(reversed(seen), k)) == window[:k]:
            return k, window[k:]
    # seen contains `first` further back: overlap is only that far-back run
    return 0, window
```
(Keep the O(1)-ish first-line reject path so a silent-then-burst container doesn't scan 2000×2000. Worst-case k-scan is bounded by `OVERLAP_CAP`.)

Container restart: `uptime_now < uptime_at_prev_poll` → reset that container's `_seen` deque and `_since_cursor` (fresh lifecycle; the container's log stream restarted, so `since` would be invalid).

Keep `MAX_LINES_PER_POLL` but default 200 → 2000 and mark: `# ponytail: hard cap; lines beyond 2000/poll/interval are lost on firehose containers — raise if that's a real load`.
Keep `LogCollectorConfig` env parsing; keep `create_log_collector`? NO — delete it (N1, zero refs).

Also fix the lifespan wiring in `app/api/app.py` (T1 area, lines ~64-67) to be guarded like the scaling loop:
```python
if config.log_collector_enabled and not config.fake_orchestrator:
    app.state.log_collector = LogCollector(get_orchestrator(), config=...)
    task = asyncio.create_task(app.state.log_collector.run())
```
(i.e. H4: never construct the collector when fake mode is on and never crash boot when Docker is absent — wrap the orchestrator fetch in the same try/except shape as the scaling block.)

**Step 7.4** Update `tests/test_api_integration.py:529` and `:572`: the static single-line assertions become startswith-based (fake now returns incrementing lines): e.g. `assert body["items"][0]["message"].startswith("log line")`. Adjust any other assertion that pinned exact line count (tail semantics now: each poll of a fresh container adds one line — verify actual behavior and set the assert to match; do not weaken to `>= 0` if an exact count is achievable).

**Step 7.5** Verify:

```powershell
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests/test_log_collector.py tests/test_log_api.py tests/test_api_integration.py -q
```
All green. Manually exercise the dedup path once by running `python -m pytest tests/test_log_collector.py -q -s` and eyeballing the fake line counters (or trust the 6 unit tests).

**Step 7.6** Commit: `fix(console-utils): collector since-cursor dedup, no silent loss`

---

### Task 8 — Exec WS hardening (M2, M3, M4, M5, M6, L10)

**Step 8.1 (test first)** In the exec WS test file (locate: `rg -l "exec/ws" backend/tests`), add:

```python
def test_exec_ws_rejects_no_token(anon_client):
    import json
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with anon_client.websocket_connect("/api/containers/cid-1/exec/ws"):
            pass
    assert excinfo.value.code == 1008
```
(Verified probe: TestClient re-raises `WebSocketDisconnect` carrying the pre-accept close code. If the fixture name differs — `anonymous_client` — use that.)

**Step 8.2** Reorder the exec route in `backend/app/api/routes/containers.py`:
1. Parse token query param → `get_current_user` equivalent FIRST (before `websocket.accept()`).
2. `require_container_access(..., action="write")` (exec is a write).
3. Only then `await websocket.accept()`.
4. On any failure BEFORE accept: `await websocket.close(code=1008, reason="Unauthorized")` and return. (Starlette TestClient: client sees `WebSocketDisconnect(code=1008)`.)
5. `emit_audit_log("container.exec")` (from T6) after access check.
6. Keep the JWT-in-query-string transport (websocket browsers can't set headers; the existing log WS does the same).

**Step 8.3** Surface exec-start failures (M6): wrap the `stream_exec` call; on exception, before closing:
```python
await websocket.send_text("Could not start a shell in this container. Make sure it is running and a shell (sh) is installed.")
await websocket.close(code=1011)
```

**Step 8.4** Fix the reader/cancel leak in `docker_orchestrator.py` (lines ~790-801):
```python
def _reader() -> None:
    try:
        while True:
            chunk = exec_runtime.read()
            if not chunk:
                break
            try:
                asyncio.run_coroutine_threadsafe(queue.put(chunk), loop).result(timeout=30)
            except (TimeoutError, RuntimeError):
                break
    finally:
        # always release the socket + semaphore slot, even if the queue died
        try:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop).result(timeout=5)
        except Exception:
            pass
        exec_runtime.close()
```
And in the route's `finally`: `await asyncio.to_thread(...)` is unnecessary if the reader did its cleanup; just let the stream finish. The semaphore `release()` already happens in the route `finally` — confirm order: reader join (with a timeout) → release.

**Step 8.5** Move blocking Docker I/O off the event loop (M3): in the route, wrap `orchestrator.resize_exec(...)` and the stdin writes — the orchestrator's `stream_exec` already reads via the thread; only `exec_create`/`exec_start` (called inside `stream_exec` start) and `resize_exec` hit the loop. Wrap those:
```python
await asyncio.to_thread(lambda: executor_start_fn)   # if stream_exec's start phase is separable
```
If `stream_exec` cannot be cheaply restructured (its start phase is inline), acceptable minimal fix: move ONLY `resize_exec` and any direct blocking calls in the route to `to_thread`, and leave a `# ponytail: exec_create/exec_start run on the loop (3 HTTP calls per session, negligible vs. keystroke writes below)` comment. Keystroke writes MUST go through `to_thread` (per-keystroke blocking):
```python
await asyncio.to_thread(stdin_write, data)
```

**Step 8.6** Semaphore + lifecycle (M4) in the route:
```python
try:
    await asyncio.wait_for(_exec_semaphore.acquire(), timeout=10)
except TimeoutError:
    await websocket.close(code=1013, reason="Too many concurrent terminals, try again shortly")
    return
```
(Keep `release()` in `finally`.) Session cap:
```python
EXEC_MAX_SESSION_SECONDS = int(os.getenv("VELA_EXEC_MAX_SESSION_SECONDS", "3600"))
```
`remaining = EXEC_MAX_SESSION_SECONDS`; loop the read with `asyncio.wait([queue_task], timeout=remaining)`; on expiry send `"[session expired]"` + `close(code=1000, reason="Session timeout")`.

**Step 8.7** Resize validation (L10):
```python
height = int(msg.get("height", 0)); width = int(msg.get("width", 0))
if 1 <= height <= 500 and 1 <= width <= 500:
    await asyncio.to_thread(orchestrator.resize_exec, exec_id, width, height)
```
(wrap the int() in try/except ValueError → ignore + `# ponytail: JSON-shaped shell input can still be swallowed; binary resize frames would fix it`)

**Step 8.8** Verify:

```powershell
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests -q -k "exec or terminal"
```

**Step 8.9** Commit: `fix(console-utils): exec WS auth-first, leak-free, off-loop I/O`

---

### Task 9 — (folded into Task 5) 

Enum query validation lives in T5; no separate task. (Placeholder kept so task numbering stays stable against the review doc.)

---

### Task 10 — Frontend: audit loop, typing, terminal guard (H2, N2, L3)

**Step 10.1** `frontend/src/pages/AuditLogPage.tsx`: replace the `reqSeq` state machinery (lines 30-51) with a ref:

```tsx
const requestSeq = useRef(0);

const load = useCallback(async (params: AuditLogQueryParams) => {
  const seq = ++requestSeq.current;
  setLoading(true);
  setError(null);
  try {
    const data = await getAuditLog(params);
    if (seq === requestSeq.current) setEntries(data.items);
  } catch (err) {
    if (seq === requestSeq.current) setError(message(err));
  } finally {
    if (seq === requestSeq.current) setLoading(false);
  }
}, []);

useEffect(() => { load(filterParams); }, [load, filterParams]);
```
(`filterParams` = memoized object built from `useSearchParams` — stable identity when params are equal. Import `AuditLogQueryParams` from `client.ts`; drop `params as any`. `AuditLogQueryParams` must include `user_id?` even though the API ignores it — or omit to match API reality; check client.ts:1505 and align page ↔ API, not the plan.)

**Step 10.2** `frontend/src/components/workloads/ContainerTerminal.tsx` (lines ~36-52): dispose guard so a StrictMode remount (or unmount-during-flight) can't write into a dead term:

```tsx
let disposed = false;
// onMessage/onClose/onError handlers: term.write only if (!disposed)
return () => { disposed = true; term.dispose(); fit.dispose(); ws.close(); };
```

**Step 10.3** `frontend/src/api/client.ts:682`: replace
```ts
const chunk = event.data instanceof ArrayBuffer ? new Uint8Array(event.data) : new TextEncoder().encode(String(event.data));
```
with
```ts
const chunk = new Uint8Array(event.data as ArrayBuffer);
```
(the handler's earlier branch guarantees binary: `ws.binaryType = "arraybuffer"` is set at :678 and the text case returns before :682 — AGENTS.md prefers narrowing over `instanceof`.) If the text branch really does fall through to :682, keep a ternary but use a type-guard: `typeof event.data === "string" ? ... : new Uint8Array(event.data)`.

**Step 10.4** Verify:

```powershell
cd F:\lolo\fac\Vela\frontend; npm run build; npm run lint
```
Manual: `npm run dev`, open `#/audit` — entries render once, no request flood (DevTools network).

**Step 10.5** Commit: `fix(console-utils): audit page refetch loop, terminal guard, typed params`

---

### Task 11 — E2E hardening (L4)

**Step 11.1** `frontend/e2e/terminal.spec.ts`: after the existing visibility assertions, when a container button IS present:

```ts
await terminalPane.getByRole("button", { name: /open terminal/i }).click();
await expect(page.locator(".xterm")).toBeVisible();
const input = page.locator(".xterm-helper-textarea");
await input.click();
await input.pressSequentially("echo vela-e2e\n", { delay: 20 });
await expect(page.locator(".xterm")).toContainText("vela-e2e", { timeout: 10_000 });
```
(The fake orchestrator's shell echoes input — verify `fake_orchestrator.py` exec behavior: if it only prints the prompt and ignores stdin, extend the fake to echo a line per input command (one-line change in the fake's stdin handler) so the test asserts a real round-trip. Prefer extending the fake over weakening the test.)

**Step 11.2** Run:

```powershell
cd F:\lolo\fac\Vela\frontend; npm run test:e2e -- e2e/terminal.spec.ts
```
(Ensure no dev server on 8000/5173 first — Playwright `reuseExistingServer` is off.)

**Step 11.3** Commit: `test(console-utils): terminal e2e asserts command output`

---

### Task 12 — Hygiene, docs, full gate (M3-partial, M12, N1-N10)

**Step 12.1** Delete dead code:
- `backend/app/core/logging/collector.py:167-170` — `create_log_collector` (zero refs; the lifespan builds `LogCollector` directly).
- `backend/app/core/containers/orchestrator.py:6` — unused `dataclass` import.
- `backend/app/api/routes/containers.py:~1200` — unused `done` variable.
- `collector.py` — the always-true `if lines:` guard.
- `docker_orchestrator.py:20` — move `logger = logging.getLogger(...)` to after imports.
- `containers.py:66` — import-order nit (group with other app imports).
- Test files under `tests/test_log_*` — add `from __future__ import annotations` at top (match neighboring test modules) and drop the three redundant local `import asyncio` lines.

**Step 12.2** README: add rows to the env-var table for `VELA_LOG_COLLECTOR_ENABLED`, `VELA_LOG_POLL_INTERVAL_S`, `VELA_LOG_MAX_LINES_PER_POLL`, `VELA_EXEC_MAX_SESSION_SECONDS` (short one-line descriptions, matching table style).

**Step 12.3** Deslop pass over the whole branch diff (per AGENTS.md): `git diff main...HEAD` — remove accidental comments, abnormal try/except on trusted paths, `any` casts added only to silence types. (N2 `as any` removals already done in T5/T10; sweep for stragglers.)

**Step 12.4** FULL GATE (must all be green before declaring done):

```powershell
# backend
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests -q        # workdir F:\lolo\fac\Vela\backend
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m alembic heads         # single head
# frontend
cd F:\lolo\fac\Vela\frontend
npm run build
npm run lint
npm run test:e2e
```

**Step 12.5** Verify the audit-test soundness unknown: `test_audit_container_actions.py` / `test_audit_user_actions.py` open sessions via `get_session_factory()` + `asyncio.run()`. After the gate, if those tests pass, confirm they actually read the SAME in-memory DB as the app (they assert on persisted rows, so a pass is evidence). If they fail with "no such table" or empty results, the env-var engine is a separate in-memory DB — fix the tests to use the fixture-provided session factory instead of `get_session_factory()`.

**Step 12.6** Commit: `chore(console-utils): hygiene, deslop, env docs`

---

## Self-review notes (done at plan-writing time)

- C1-C5, H1-H5, M1-M8, M10, L1, L3, L4, L10, N1-N2 all map to tasks; M9/M11/L2/L5-L9 accepted with reasons (see "Accepted deviations"); nothing in the findings table is unaddressed.
- Verified facts used in exact patches: `require_container_access` at `access.py:58` (raises `ContainerNotFoundError` for foreign → maps to 404); TestClient pre-accept close → `WebSocketDisconnect(code=1008)` (live-probed); starlette `close()` on unaccepted WS is legal (probed); conftest StaticPool single-connection in-memory (verified); `bootstrap_env` is `setdefault` (verified) so the T4 env toggle works; 0014/0016 head graph (verified via alembic); `c589b60^2` index.css = 2976 clean main lines, `^1` = 2667 clean branch lines (verified).
- Ordering: T1-T3 unblock everything else; T4 before T7 (collector must be test-disabled before its rewrite lands); T5 before T10 (LogQueryParams shape); T6 before T8 (exec audit emission lives in the reordered route); T11 last before T12 (needs E2E env clean + fake echo).
- Open items for the executor (do NOT block): exact seeded container id for the T5 test (derive from existing run-container test pattern, don't hardcode blindly); `export` query-param key name (`q` vs `search`) — confirm against `client.ts` before finalizing T5.2; fake shell stdin echo for T11.
