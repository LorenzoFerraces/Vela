# Vela Efficiency Improvement Plan

Last updated: 2026-09-01 (branch `f/performance-improvements`, re-baselined against dev).
Status markers: `[ ]` pending, `[x]` done, `[~]` partial.

Findings were re-verified against the current codebase on 2026-09-01; line numbers
reference that state and will drift as tasks land.

## 1. Backend

### 1.1 Container list path (highest impact, small diffs)

The list path is hit by `GET /containers/`, the 15 s monitor loop
(`container_monitor.py:185`), and the 5 s log collector (`collector.py:134`) —
so its per-container cost runs continuously, not just on user action.

- [x] **Drop `container.reload()` from `list()`** — `docker_orchestrator.py:659`
  does a full `docker inspect` per container (N+1 Docker API calls). Serve
  status/image/ports from the `/containers/json` list payload; health already
  has a per-container endpoint (`GET /{id}/health`). Other `reload()` call
  sites (lines 497, 533, 561, 581, 1065) are single-container paths and can
  stay.
- [x] **Batch `_enrich_container_source_labels`** — `containers.py:426-465`
  does 2+ DB round-trips per listed container (membership role, optional
  user, template name), and `latest_source_by_container_ids` re-runs
  `list_project_ids_for_user` even though the caller just ran it. Replace
  per-container awaits with one batched `SELECT` for
  `(container_id → project_id, role)` plus one for template names.
- [x] **Paginate `GET /containers/`** — `containers.py:483-500` returns an
  unbounded list. `/logs/` and `/deployments/` already paginate; match them.
  Also bound the log collector's sequential per-container `logs()` calls
  (`collector.py:142,163`) with `asyncio.gather` + a small semaphore.
- [x] **Index `deployment_records.container_id`** — `models.py:287` has no
  index; it is the filter in `deployment_history.py:107-114` (hot `IN (...)`)
  and `container_monitor.py:225-231`. One alembic migration, composite
  `(container_id, created_at desc)`.

### 1.2 LLM / git analysis pipeline

The commit-keyed cache (`app/core/llm/cache.py`) only caches the LLM HTTP
call. A "hit" still pays git clone + full tree scan + `analyze_project`
(2–3×) + prompt build, because the cache key requires the head commit, which
requires the clone (`git_source_analysis.py:599-613`, same shape in
`stacks/repo_analysis.py:342-388`).

- [ ] **Cheap commit resolution**: `git ls-remote <url> <branch>` instead of
  cloning to find the sha.
- [ ] **Cache the full result** (including the deterministic extraction —
  context summary + detected facts) keyed on `(url, branch, sha)`; a hit
  returns without clone/scan. Clone only when the LLM call is actually made.
- [ ] **Compute `analyze_project` once** per request and thread the
  `ProjectInfo` through `_collect_context_excerpts` (line 289),
  `_detected_facts_block` (371), `_enrich_with_local_detection` (441).
- [ ] **Move sync work off the event loop** (clone is already in
  `asyncio.to_thread`; these were missed):
  - `head_commit` subprocess — `git_ops.py:106-119`
  - context building / FS walks — `git_source_analysis.py:168-295`
  - LLM cache file I/O — `cache.py:29-84`
- [ ] **Stop rewriting the whole cache file per store** — `cache.py:63-84`
  reads, mutates, and `json.dumps` the entire 500-entry dict per store.
  One SQLite table (or per-key files) replaces it; also fixes the
  single-writer assumption flagged in the existing ponytail comment.
- [ ] **Shared `httpx.AsyncClient`** — module-level client for
  `llm/client.py:28` and `registry_image_suggestions.py:46` (currently a new
  TCP+TLS handshake per call).

### 1.3 Misc backend

- [ ] **GZipMiddleware** — one line in `create_app` (`app.py:108`, currently
  CORS only); list/log/JSON payloads ship uncompressed.
- [ ] **`stream_exec` setup off the loop** — `exec_create`/`exec_start`
  (`docker_orchestrator.py:774-784`) are 3 blocking Docker HTTP calls per
  terminal open; wrap in `asyncio.to_thread` (reader-thread model already
  exists, only the setup calls move). See ponytail comment at
  `containers.py:1225`.
- [ ] **Cap build log in memory on the error path** —
  `docker_orchestrator.py:984-1027` accumulates the full build stream in
  `log_parts` and joins it on failure; keep the trailing N KB instead.

## 2. Frontend

- [x] **Batch `ContainerLogPanel` WS flush** — `ContainerLogPanel.tsx:88-101,122-131,178-197`
  re-renders per WS message: re-splits the 256 KB buffer and diffs up to
  1500 keyed `<span>` lines. Accumulate in a ref, flush to state on rAF /
  ~100 ms. Worst jank surface in the app.
- [x] **Lazy-load `ContainerTerminal`** — `WorkloadsTable.tsx:10,453` pulls
  xterm into a ~286 KB chunk shared by ContainersPage + DashboardPage for an
  opt-in per-row feature. `React.lazy(() => import('./ContainerTerminal'))`
  removes it from the critical path.
- [x] **Turn the existing request cache on** — the TTL cache + in-flight
  dedup in `src/api/client.ts` (lines 7-10, 162-232) had **zero call sites**.
  Enabled `cache: true` inside `listContainers`/`listProjects`/
  `listScalingPolicies`; added **write invalidation** (any successful non-GET
  clears the read cache) so start/stop/delete never shows a stale list. A
  Dashboard→Containers→Teams loop now fetches each list once.
- [x] **Debounce `LogsPage` search** — `LogsPage.tsx:241 → 112-115` fires an
  API request per keystroke. Reuse the 320 ms debounce pattern from
  `useDeploySourceSelection.ts:93-96`.
- [ ] **Memoize `WorkloadsTable` rows** — `WorkloadsTable.tsx:219-463` renders
  rows as inline fragments; any table state change (`copiedRowId`,
  `terminalContainerId`, `rowBusyId`, ...) re-renders every row with fresh
  inline props. Extract a `React.memo` row component with per-row expand/
  terminal state.
- [ ] **Memoize StackBuilder graph derivation** — `StackBuilderPage.tsx:791-817,1088-1098`
  and `StackVisualizer.tsx:195-228` rebuild the ReactFlow graph on every
  keystroke in any service field. Derive nodes/edges from
  `(name, depends_on)` only, via `useMemo`; memoize `ServiceEditForm`.
- [ ] **Split `src/api/client.ts`** (1608 lines) into domain modules
  (`api/containers.ts`, `api/stacks.ts`, `api/projects.ts`, `api/auth.ts`,
  `api/images.ts`) over a shared core; keep re-exports so imports don't
  churn. Delete dead `src/pages/containers/useContainerList.ts` (imported
  nowhere).
- [ ] **Small**: rAF-debounce the unthrottled `ResizeObserver` in
  `ContainerTerminal.tsx:43-47`; module-level `TextEncoder` for the exec WS
  string branch (`client.ts:719`, pattern already in
  `ContainerLogPanel.tsx:12`).
- [ ] **Split `TeamsPage.tsx`** (729 lines) into list / detail /
  invitations subcomponents.
- [ ] **Product decision**: lists never refresh after mount (no polling
  anywhere in `src/`). Consider a visibility-aware 15–30 s poll or
  refetch-on-focus for the workloads list; skip if staleness is acceptable.

## 3. Roadmap

Ordered by impact-per-diff; each item is independently shippable and testable.

1. **Container list path** (1.1, all four) — biggest runtime win, smallest
   diffs. The 15 s / 5 s background loops benefit even with no users.
2. **Frontend quick wins** (log panel batching, lazy terminal, enable cache,
   debounce logs search) — user-visible jank and duplicate requests.
3. **LLM cache rework** (1.2) — its own task; touches the analysis pipeline
   end to end (cheap sha, full-result cache, single `analyze_project`,
   thread offload, storage).
4. **Rendering memoization + client.ts split + TeamsPage split** — change
   isolation and smoothness.
5. **Misc** (GZip, stream_exec, build-log cap, small frontend items).

## 4. Dropped (re-evaluated 2026-09-01)

- **react-window / react-virtual** — no list is large enough: logs 100/page,
  audit 50/page, workloads bounded by pagination (1.1). The only DOM strain
  is the 1500-span log panel, fixed by batching (§2 item 1). Revisit if a
  genuinely unbounded list appears.
- **Redis / backend service caching** — YAGNI. The hotspots are Docker N+1,
  DB N+1, and the un-cached clone, none of which Redis fixes. Revisit for a
  multi-node deploy.
- **Vague "performance monitoring" phase** — replaced by the concrete
  verification targets below.
- **Denormalization** — no evidence of a relationship hot enough to warrant
  it; batched queries (1.1) cover the cost.

## 5. Verification

Per repo convention: `python -m pytest` (backend) and the Playwright E2E suite
after each task; lint + typecheck on both sides.

Measurable targets (before/after, same fixture):

- Docker API calls per `GET /containers/` at N containers: N+2 → 2 (no
  `reload()` per container).
- DB round-trips per `GET /containers/`: ~3N → O(1) batched queries.
- Repeated LLM analysis of an unchanged repo: no clone on cache hit.
- Request count across a Dashboard→Containers→Teams navigation loop:
  3× containers / 2× projects / 2× policies → 1× each.
- Containers/Dashboard first-load JS: xterm out of the initial chunks.
- Log panel renders under sustained output: per-WS-message → per-frame.
