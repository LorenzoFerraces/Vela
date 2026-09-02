# Resource Management — Pre-Merge Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps found in the 2026-09-02 review of the resource-management branch before it merges to `dev`: missing passthrough test, branch-introduced ruff findings, design-system violations in the resource UI, undocumented env vars, and stale plan docs.

**Context:** The branch `f/resource-management` implements `2025-08-03-resource-limits.md`, `2025-08-03-resource-dashboard.md`, and `2026-08-16-team-storage-quota.md`. All three features are built and green (pytest 455 passed, E2E 48 passed at review time). This plan fixes review findings only — no behavior changes except the Network Tx chart line.

**Tech Stack:** FastAPI, pytest, React, TypeScript, recharts, plain CSS

## Global Constraints

- Python 3.12+, TypeScript, exact npm versions (no ^ or ~). No new dependencies.
- Backend style: explicit, typed, match surrounding modules. Tests: real wiring over mocks (repo convention).
- Frontend UI standards (AGENTS.md): **no raw hex/rgba in components or inline styles** except library props that cannot consume CSS variables (xyflow, xterm, and — after Task 3 — recharts in `MetricChart.tsx`); keep exception hex values in sync with the dark theme tokens in `frontend/src/index.css` `:root`. **0 border-radius everywhere.** Page/component-specific styles live in a separate CSS file imported by that component — do not grow `index.css`.
- Design tokens (dark theme `:root`): `--border: #5a4b7a`, `--text: #e9e4f2`, `--text-muted: #9a8fb8`, `--text-heading: #f1edf9`, `--accent: #bc7fed`, `--ok: #4ade80`, `--warn: #fbbf24`, `--info: #9aa5b4`, `--error: #ef4444`.
- Commit each task separately. Conventional-commit subjects, match repo style.
- Verification commands: backend `python -m pytest tests -q` + `ruff check .` (run from `backend/` with `F:\lolo\fac\Vela\.venv\Scripts\python.exe`); frontend `npm run build` + `npm run lint` (from `frontend/`).

---

## Task 1: Add resource-limit passthrough tests for all source kinds

**Files:**
- Modify: `backend/tests/test_api_integration.py`

**Problem:** Plan `2025-08-03-resource-limits.md` Task 2 step 2.1 specifies `test_run_resource_limits_pass_through_all_source_kinds`; it was never written. Only the image path has limit-passthrough coverage (via `test_run_from_image_with_resource_limits`). The `dockerfile_template` and `git` deploy paths (`run_from_user_source` in `backend/app/api/routes/containers.py`, call sites at ~lines 955 and 1042) have no dedicated test.

### Step 1.1: Write the test

Add `test_run_resource_limits_pass_through_all_source_kinds` to `backend/tests/test_api_integration.py`, after the existing `test_run_from_image_resource_limits_optional` test (line ~248). It must cover all three `run_from_user_source` paths and assert `fake_orchestrator.last_deploy_config` after each:

1. **image**: `POST /api/containers/run` with `{"source_kind": "image", "image_ref": "nginx:alpine", "cpu_limit": 0.5, "memory_limit": 256}` → 200; assert `last_deploy_config.cpu_limit == 0.5` and `.memory_limit == 256`.
2. **dockerfile_template**: follow the existing `test_run_from_dockerfile_template` pattern in the same file (line ~463): monkeypatch `VELA_PUBLIC_ROUTE_DOMAIN`/`VELA_PUBLIC_URL_SCHEME`, create a template via `POST /api/dockerfiles/` (`{"name": "limits-tpl", "contents": "FROM alpine:3.20\n"}`), then `POST /api/containers/run` with `{"source_kind": "dockerfile_template", "dockerfile_template_id": <id>, "public_route": true, "container_port": 80, "cpu_limit": 1.0, "memory_limit": 512}` → 200; assert limits on `last_deploy_config`.
3. **git**: monkeypatch `app.core.build.default_image_builder.git_shallow_clone` — reuse the existing `_stub_git_shallow_clone` helper already defined in this file (used by `test_run_from_git_url`, line ~513) — plus the same public-route env vars, then `POST /api/containers/run` with `{"source": "https://github.com/org/repo.git", "git_branch": "develop", "public_route": true, "container_port": 80, "cpu_limit": 2.0, "memory_limit": 1024}` → 200; assert limits on `last_deploy_config`.

Use distinct limit values per path (as above) so a stale `last_deploy_config` from a previous sub-step cannot mask a failure. Fixtures: `api_client`, `fake_orchestrator`, `monkeypatch` (all exist in `backend/tests/conftest.py`). Match the file's existing test style (type-annotated args, plain asserts).

- [x] Add the test

### Step 1.2: Verify

- [x] Run `python -m pytest tests/test_api_integration.py -q` — new test passes, no regressions in the file
- [x] Run `python -m pytest tests -q` — full suite green before committing
- [x] Commit: `test: resource limit passthrough for all run source kinds`

---

## Task 2: Remove branch-introduced ruff findings

**Files:**
- Modify: `backend/alembic/versions/0019_merge_resource_management.py`
- Modify: `backend/app/api/routes/projects.py`

**Problem:** The branch added 3 ruff F401 findings on top of the dev baseline (dev: 26 findings, branch: 28). Two are genuinely new; one is a moved pre-existing finding — remove all three.

### Step 2.1: Fix the no-op merge migration

`backend/alembic/versions/0019_merge_resource_management.py` has unused `from alembic import op` (line 12) and `import sqlalchemy as sa` (line 13). Delete both import lines. Keep the module docstring, `revision`, `down_revision` (the 2-tuple), `branch_labels`, `depends_on`, and the empty `upgrade()`/`downgrade()` functions exactly as they are.

### Step 2.2: Fix the unused import in projects.py

`backend/app/api/routes/projects.py` line 52: `from app.db.models import Project, User` — `Project` is unused (ruff F401). Verify `User` is actually used in the file before editing; keep `User` if so (expected), and if `User` is also unused remove the whole import line instead.

### Step 2.3: Verify

- [x] Run `ruff check .` from `backend/` — no findings in `0019_merge_resource_management.py` or `projects.py`; total finding count ≤ 25
- [x] Run `F:\lolo\fac\Vela\.venv\Scripts\python.exe -m alembic heads` from `backend/` — still a single head `0019_merge_resource_management` (import removal must not break the migration module)
- [x] Run `python -m pytest tests/test_projects_api.py -q` (or the closest project-route test file if that name doesn't exist — check `backend/tests/`) to confirm `projects.py` still imports cleanly
- [x] Commit: `fix: remove unused imports flagged by ruff`

---

## Task 3: Frontend design-token pass on the resource UI + Network Tx line

**Files:**
- Modify: `frontend/src/pages/ResourceDashboardPage.tsx`
- Modify: `frontend/src/pages/containers/ResourceUsagePanel.tsx`
- Modify: `frontend/src/components/charts/MetricChart.tsx`
- Create: `frontend/src/pages/resource-dashboard.css`
- Create: `frontend/src/pages/containers/resource-usage-panel.css`
- Modify: `AGENTS.md` (repo root)

**Problem:** The resource UI was implemented from the plan's inline-hex snippets and violates the repo's design standards (AGENTS.md UI standards): raw hex colors in inline styles, `borderRadius: 8` (repo rule: 0 border-radius everywhere), no use of the CSS design tokens. Additionally `network_tx_bytes` is collected and mapped into `chartData` but never charted — the Network I/O card shows Rx only.

### Step 3.1: Move ResourceDashboardPage styles to tokens

`frontend/src/pages/resource-dashboard.css` (new, imported by `ResourceDashboardPage.tsx`) holds the page-specific classes. Required classes (names may be refined to match surrounding conventions, but coverage is required):

- `.metrics-toolbar` — flex row, gap 8px, bottom margin 16px, centered items; its "Time range:" label uses `color: var(--text-muted)`
- `.metrics-grid` — 2-column grid, 16px gap (both the loading-skeleton wrapper and the chart cards use it)
- `.metrics-card` — `border: 1px solid var(--border)`; padding 16px; **no border-radius** (repo radius is 0)
- `.metrics-card__title` — margin `0 0 8px`, font-size 14px, `color: var(--text-heading)`
- `.metrics-empty` — padding 40px, centered, `color: var(--text-muted)`; inner hint 14px

In `ResourceDashboardPage.tsx`: delete every inline `style` prop that carries raw hex or border-radius; use the classes above instead. Keep: existing `dashboard-page*`, `btn*`, `containers-banner*`, `skeleton--metrics-chart` classes, the `requestSequence` race guard, all labels/text (E2E locators depend on them), and the `marginLeft: 'auto'` on the Refresh button may move to the CSS (e.g. `.metrics-toolbar__refresh { margin-left: auto; }`).

Chart `color` props stay hex (recharts cannot consume CSS variables) but must be the dark-theme token values: CPU `#bc7fed` (--accent), Memory Usage `#4ade80` (--ok), Memory Percent `#fbbf24` (--warn).

### Step 3.2: Move ResourceUsagePanel styles to tokens

`frontend/src/pages/containers/resource-usage-panel.css` (new, imported by `ResourceUsagePanel.tsx`). Replace the inline raw-hex styles (e.g. lines with `#6b7280`, `#e5e7eb`, `borderRadius: 8`, `#374151`, `#3b82f6`) with classes using `var(--text-muted)`, `var(--border)`, `var(--text-heading)`, and the accent for the container-name buttons — **or** reuse an existing link/button class from `index.css` if one fits (check for a `.link`-style class before inventing one). No border-radius. Keep the existing `.resource-usage__quota` class (already in `index.css`) and all text content/structure (E2E `teams.spec.ts` and dashboard specs may reference panel text).

### Step 3.3: MetricChart multi-series + token-synced hex

`frontend/src/components/charts/MetricChart.tsx`:

- Add an optional prop `series?: { dataKey: string; label: string; color: string }[]`. When provided, render one `<Line>` per series (monotone, `dot={false}`, `strokeWidth={2}`); when omitted, behavior must stay exactly as today (single series from `dataKey`/`color`/`label`).
- Grid stroke: replace `#e5e7eb` with `#5a4b7a` (dark theme `--border`).
- Reference line keeps `#ef4444` (= dark theme `--error`).
- Axis tick + tooltip text: use `#9a8fb8` (dark theme `--text-muted`) for tick fills so charts are readable on the dark background.
- Add a short comment above the hex values noting they must stay in sync with the dark theme tokens in `index.css` (same convention as the documented xyflow/xterm exceptions).

### Step 3.4: Network I/O card shows Rx and Tx

In `ResourceDashboardPage.tsx`, the Network I/O card uses `series`:

```tsx
<MetricChart
  data={chartData}
  label="Network I/O"
  yAxisLabel="Bytes"
  formatValue={formatBytes}
  series={[
    { dataKey: 'networkRx', label: 'Network Rx', color: '#9aa5b4' },
    { dataKey: 'networkTx', label: 'Network Tx', color: '#bc7fed' },
  ]}
/>
```

(--info and --accent hex, per Step 3.1 rule.) `chartData` already carries `networkTx`.

### Step 3.5: AGENTS.md exception list

In the repo-root `AGENTS.md`, UI standards section, the sentence listing hex exceptions ("the only exceptions are library props that cannot consume CSS variables (xyflow in `StackVisualizer.tsx`, xterm theme in `ContainerTerminal.tsx`)") — add recharts in `MetricChart.tsx` to that exception list, keeping the "keep those hex values in sync with the dark theme tokens" clause.

### Step 3.6: Verify

- [x] `npm run build` — clean (tsc -b + vite)
- [x] `npm run lint` — no new findings (one pre-existing `react-hooks/exhaustive-deps` warning in `UserMenu.tsx` may remain)
- [x] Grep the three touched components for `borderRadius` and hex color literals in JSX `style` props — none remain (MetricChart hex allowed per Step 3.5)
- [x] Commit: `fix: resource UI design tokens and network tx chart`

---

## Task 4: Documentation updates (README env vars + plan docs)

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2025-08-03-resource-limits.md`
- Modify: `docs/superpowers/plans/2025-08-03-resource-dashboard.md`
- Modify: `docs/superpowers/plans/2026-08-16-team-storage-quota.md`
- Modify: `docs/superpowers/plans/2026-09-02-resource-management-premerge-fixes.md` (checkboxes only, at the very end)

### Step 4.1: README env var table

In `README.md` the env var table (around line 107), add two rows after the `VELA_TEAM_STORAGE_QUOTA_BYTES` row, matching the table's column style:

| `VELA_METRICS_INTERVAL_SECONDS` | Background container-metrics collector poll interval in seconds (default `30`) |
| `VELA_METRICS_RETENTION_DAYS` | Days to retain stored container metrics (default `30`) |

### Step 4.2: resource-limits plan

In `docs/superpowers/plans/2025-08-03-resource-limits.md`:

- Check every remaining `- [ ]` task-step checkbox to `- [x]` (the Self-Review section is already checked).
- Append a short **Status (2026-09-02)** section after the Corrections section: all tasks implemented on `f/resource-management`; note that the Task 2 step 2.1 passthrough test was missing at first review and added 2026-09-02 (see `2026-09-02-resource-management-premerge-fixes.md` Task 1); `RunFromSourceRequest` now lives in `frontend/src/api/containers.ts` (API client refactor, re-exported from `client.ts`); a `cpu_limit` finiteness validator was added per review findings.

### Step 4.3: resource-dashboard plan

In `docs/superpowers/plans/2025-08-03-resource-dashboard.md`:

- Check every remaining `- [ ]` checkbox (task steps and Self-Review) to `- [x]`.
- Append a short **Status (2026-09-02)** section after the Corrections section: all tasks implemented; corrections to stale facts — alembic head is now `0019_merge_resource_management` (0017 is in the chain, no longer orphaned at head `0016`); Task 3.3's `routes/__init__.py` export step was not done (file is docstring-only, `app.py` imports the submodule directly); the metrics client lives in `frontend/src/api/metrics.ts` (re-exported from `client.ts`); `GET /api/metrics/usage` additionally returns team storage quota fields (see `2026-08-16-team-storage-quota.md`); the Task 6 inline-hex UI snippets were superseded by design-token CSS (see `2026-09-02-resource-management-premerge-fixes.md` Task 3).

### Step 4.4: team-storage-quota plan

In `docs/superpowers/plans/2026-08-16-team-storage-quota.md`: check every remaining `- [ ]` checkbox to `- [x]` and append a one-line **Status (2026-09-02)**: fully implemented and verified on `f/resource-management` (pytest + E2E green at 2026-09-02 review).

### Step 4.5: this plan's checkboxes

Check the `- [ ]` step checkboxes in this file as the tasks complete (do this last, after Task 5 verification).

- [x] Steps 4.1–4.4 done
- [x] Commit: `docs: mark resource plans complete, document metrics env vars`

---

## Task 5: Full verification gate

**No code changes.** If anything fails, report it — do not fix (the controller routes fixes).

### Step 5.1: Backend

- [x] `python -m pytest tests -q` from `backend/` (venv python) — all pass
- [x] `ruff check .` — no findings in `0019_merge_resource_management.py` / `projects.py`; total ≤ 25
- [x] `mypy app/ tests/` — only the 12 pre-existing findings (missing docker/yaml/boto3 stubs + conftest packaging)

### Step 5.2: Frontend

- [x] `npm run build` clean; `npm run lint` — only the pre-existing `UserMenu.tsx` warning
- [x] Ensure ports 8000/5173 are free, then `npm run test:e2e` — full suite green

### Step 5.3: Compose

- [x] `docker compose -f docker-compose.yml config -q` from repo root
- [x] If the Docker daemon is available: `docker compose up -d --build`, confirm via `docker compose ps` that `migrate` completed and `api` is `healthy`, then `docker compose down`. If Docker is unavailable in this environment, say so explicitly in the report (do not fail the task on environment limits).

### Step 5.4: Report

Write the verification results (commands, outputs/counts, compose status) to the report file. No commit.
