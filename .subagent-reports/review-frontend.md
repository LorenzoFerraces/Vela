# Frontend review — Vela (dev + security hardening)

Scope: `frontend/` only (src, e2e, config). Backend route decorators read only to build the endpoint-gap list.
Guidelines source: `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md` (fetched).

Severity counts (ranked master list): **High 3 · Medium 15 · Low 17**.

---

## 1. Ranked findings (highest first)

### HIGH

**H1 — `formatApiError` can return a non-string and crash React renders.**
`frontend/src/api/core.ts:157` — `const detail = parsed.detail ?? error.message` is cast to `string` via `JSON.parse(...) as {...}`, but FastAPI 422 validation errors return `detail` as an *array of objects*. Any page doing `{formatApiError(error)}` (all of them) then throws "Objects are not valid as a React child". One `typeof detail === 'string'` guard in the shared mapper fixes every caller.

**H2 — Clerk JS loaded from an unpinned `@latest` CDN URL.**
`frontend/src/pages/LoginPage.tsx:93` — `https://${frontendApi}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js`; a remote supply-chain change can execute arbitrary code on the login page with no lockfile. Pin the version (or self-host).

**H3 — No skip link to main content, and `main` is unlabelled.**
`frontend/src/components/Layout.tsx:8` (`<main className="main-content">`), `frontend/index.html:26`. Guideline: "include skip link for main content"; keyboard users tab through the whole navbar on every route.

### MEDIUM

**M1 — Audit date filters shift by timezone.** `frontend/src/pages/AuditLogPage.tsx:159-166` — `new Date(\`${fromRaw}T00:00:00\`).toISOString()` converts local midnight to UTC, so "From" and "To" silently select the wrong day outside UTC. Send the date as-is (`params.from_date = fromRaw`) and let the backend parse.

**M2 — Destructive stack delete uses an inline two-click "Confirm?" button, not the shared dialog.** `frontend/src/pages/StacksPage.tsx:142-149`, `:350-370` — 5s timer state, no `role="dialog"`, no focus management, ambiguous for keyboard/SR users; every other destructive action uses `ConfirmDialog`. Reuse `ConfirmDialog`.

**M3 — No unsaved-changes guard on the stack builder.** `frontend/src/pages/stacks/StackBuilderPage.tsx:391-397` (Cancel), `:248` (post-save navigate), plus browser back/refresh. Guideline: warn before navigation with unsaved changes.

**M4 — Admin tab widget is not keyboard-accessible.** `frontend/src/pages/AdminPage.tsx:22-62` — `role="tab"` buttons with no arrow-key handling / roving `tabIndex`; `role="tabpanel"` panels have no `aria-labelledby`.

**M5 — Navigation implemented as buttons in the account menu.** `frontend/src/components/UserMenu.tsx:75-99` — Settings/Audit Log are `<button onClick={() => navigate(...)}>`; no Cmd/Ctrl-click, middle-click, or copy-link. Use `<Link>` and drop the misleading `aria-haspopup="true"` / un-roled `aria-label="Account"` container.

**M6 — Three overlapping poll loops on the Containers page.** `frontend/src/pages/containers/ContainersPage.tsx:88-95` (1s deploy discovery), `frontend/src/hooks/useActiveDeployJobs.ts:30-43` (2.5s), `frontend/src/pages/containers/useWorkloadGroups.ts:53-87` (30s). Redundant requests and three sources of truth for "in flight".

**M7 — Bearer token placed in WebSocket query strings.** `frontend/src/api/containers.ts:169` (logs), `:195` (exec) — leaks the access token into server/proxy access logs. Prefer a short-lived WS ticket or cookie if the backend can support it.

**M8 — `meta theme-color` never follows the light theme.** `frontend/index.html:7` hardcodes `#120e1e` while `frontend/src/hooks/useTheme.ts:22` only swaps `data-theme`. Guideline: theme-color must match page background.

**M9 — Login page copy/locale is inconsistent with the rest of the English UI.** `frontend/src/pages/Home.tsx:22` (`formatApiError(error, 'es')`), `:33-36` ("Hola, esto es Vela", "Plataforma de despliegue").

**M10 — README E2E section is factually wrong (docs drift).** `README.md:272` claims specs use `page.route(...)` mocking and need no Postgres/Docker. `frontend/playwright.config.ts:97-120` starts a real API (SQLite) + Vite webServer; `AGENTS.md` forbids `page.route`; grep for `page.route` in `frontend/e2e/` returns zero matches. Fix the README to match the config.

**M11 — Success banners have no live region on Stacks.** `frontend/src/pages/StacksPage.tsx:396` — `role={tone === 'err' ? 'alert' : undefined}`; other pages use `role="status"` for success. Screen readers miss deploy/delete confirmations.

**M12 — Stack name form cannot be submitted.** `frontend/src/pages/stacks/StackBuilderPage.tsx:278` — `<form onSubmit={(e) => e.preventDefault()}>` with the Save button outside; Enter in the name field does nothing.

**M13 — Logs CSV export ignores the debounced search used by the table.** `frontend/src/pages/LogsPage.tsx:132` exports with `search` while `:107` displays `debouncedSearch`; exported rows can differ from what the user sees.

**M14 — Duplicated page + banner + types for Images and Builder.** `frontend/src/pages/ImagesPage.tsx:7-42` vs `frontend/src/pages/BuilderPage.tsx:16-52`; `images/ImagesMessageBanner.tsx` vs `builder/BuilderMessageBanner.tsx`; `images/types.ts` vs `builder/types.ts`. Same component with different copy.

**M15 — Responsive/consistency: tab state not deep-linkable.** `frontend/src/pages/AdminPage.tsx:12` (active tab), `frontend/src/pages/ResourceDashboardPage.tsx:25` (time range) use local state only; guideline: URL reflects state. Logs/Audit pages do this correctly.

### LOW

**L1 — Inputs lack `name` attributes.** `frontend/src/pages/LoginPage.tsx:173-195` (email/password), `frontend/src/pages/TeamsPage.tsx:86-95` (team name). Guideline: meaningful `name` + autocomplete.
**L2 — `safeNextPath` accepts protocol-relative paths.** `frontend/src/pages/LoginPage.tsx:9-10` — `"//host"` passes `startsWith('/')`; reject `path.startsWith('//')`.
**L3 — Dynamic Clerk script never removed on unmount.** `frontend/src/pages/LoginPage.tsx:86-104` — `clerkLoadPromise` and injected `<script>` persist for the session.
**L4 — Time-range buttons lack `aria-pressed`.** `frontend/src/pages/ResourceDashboardPage.tsx:85-92` — selected state conveyed by color only.
**L5 — Plain "Loading…" text instead of skeletons.** `frontend/src/pages/stacks/StackBuilderPage.tsx:309`, `frontend/src/pages/SettingsPage.tsx:193-194`, `frontend/src/pages/RequireAuth.tsx` usage at `frontend/src/auth/RequireAuth.tsx:15-17`. Other pages use skeletons (good).
**L6 — `setTimeout` highlight timers not cleaned on unmount.** `frontend/src/pages/stacks/StackBuilderPage.tsx:185`, `:368`.
**L7 — Render-phase ref assignment.** `frontend/src/pages/containers/ContainersPage.tsx:126` — `refreshRef.current = refresh` during render.
**L8 — Effect cleanup leak path in terminal.** `frontend/src/components/workloads/ContainerTerminal.tsx:27,31-39` — early return when `containerRef.current` is null or `openContainerExecWebSocket` throws skips `term.dispose()` / `fit.dispose()`.
**L9 — `useTheme` writes localStorage without try/catch** (`frontend/src/hooks/useTheme.ts:23`) while the read path is guarded (`:9-14`); throws in private mode.
**L10 — Hardcoded locale arrays for dates.** `frontend/src/pages/LogsPage.tsx:294`, `frontend/src/pages/AuditLogPage.tsx:95,307`, `frontend/src/components/charts/MetricChart.tsx:61,115` — `toLocaleString([])`/hardcoded format; guideline prefers explicit `Intl.*` with a chosen locale.
**L11 — Duplicate label mechanisms.** `frontend/src/components/workloads/WorkloadsTable.tsx:61-70` — `<label htmlFor>` plus `aria-label` on the same select; `aria-label` wins for SR users.
**L12 — Busy copy not specific.** `frontend/src/pages/SettingsPage.tsx:425` ("Working…" for Disconnect); guideline: "Disconnecting…".
**L13 — Audit action meta is a closed hard-coded list.** `frontend/src/pages/AuditLogPage.tsx:29-81` — every new backend action silently falls back to "Performed action"; `:287` variable `isSelf` actually means "target is a user".
**L14 — `historyRefreshSignal` never incremented after row operations.** `frontend/src/pages/DashboardPage.tsx:22,119` — deployment history only refreshes on the manual Refresh button.
**L15 — Dead code.** `frontend/src/pages/PlaceholderPage.tsx` (no imports anywhere); `frontend/src/api/metrics.ts:37` `getMetricSummary` and `frontend/src/api/images.ts:39` `getImageSuggestions` are exported/re-exported but never consumed.
**L16 — Oversized files with mixed concerns.** `frontend/src/pages/stacks/ServiceEditForm.tsx` (714 lines), `frontend/src/pages/teams/useTeamManagement.ts` (456), `frontend/src/pages/StacksPage.tsx` (440), `frontend/src/pages/stacks/NewStackModal.tsx` (438), `frontend/src/pages/containers/useContainerRunForm.ts` (428), `frontend/src/api/core.ts` (414), `frontend/src/pages/SettingsPage.tsx` (402), `frontend/src/index.css` (2556).
**L17 — JSDoc noise on trivial code (deslop targets).** `frontend/src/pages/BuilderPage.tsx:7-15`, `frontend/src/api/client.ts:279-286,299-305,328-335`, `frontend/src/pages/containers/BuildConfigModal.tsx` helpers, `frontend/e2e/api-helpers.ts:9-18,42-46,70-82,84-89,122-127,135-141`.

---

## 2. Web Interface Guidelines — findings grouped by file

(Only deviations; compliant items noted with ✓ where notable.)

### `frontend/index.html`
- `frontend/index.html:7` — `<meta name="theme-color" content="#120e1e">` static dark; light theme needs a swap.
- `frontend/index.html:10-13` — Google Fonts via stylesheet with `display=swap`; preconnect present ✓; no font preload (minor).
- `frontend/index.html:6` — no `user-scalable=no` / `maximum-scale` ✓.

### `frontend/src/components/Layout.tsx`
- `frontend/src/components/Layout.tsx:8` — no skip link; `main` has no `id`/`aria-label`.

### `frontend/src/components/Navbar.tsx`
- ✓ `:43` nav `aria-label="Main"`, `:66-67` icon button `aria-label` + `aria-pressed`, decorative icons `aria-hidden`.

### `frontend/src/pages/LoginPage.tsx`
- `frontend/src/pages/LoginPage.tsx:173,187` — inputs lack `name`.
- `frontend/src/pages/LoginPage.tsx:9-10` — `safeNextPath` permits `//…`.
- `frontend/src/pages/LoginPage.tsx:93` — unpinned `@latest` script.
- ✓ `:177,191` autocomplete, `:178` spellCheck off, `:198` `role="alert"`, `:208` "Signing in…", submit disabled while busy.

### `frontend/src/pages/AdminPage.tsx`
- `frontend/src/pages/AdminPage.tsx:23-44` — tabs lack arrow-key support/roving tabindex.
- `frontend/src/pages/AdminPage.tsx:47-62` — tabpanels lack `aria-labelledby`.

### `frontend/src/components/UserMenu.tsx`
- `frontend/src/components/UserMenu.tsx:75-99` — navigation via `<button>`; no `role="menu"`/`menuitem`; `aria-haspopup="true"` too vague.

### `frontend/src/pages/ResourceDashboardPage.tsx`
- `frontend/src/pages/ResourceDashboardPage.tsx:85-92` — no `aria-pressed` on segmented time-range buttons.
- `frontend/src/pages/ResourceDashboardPage.tsx:25` — time range not in URL.

### `frontend/src/pages/StacksPage.tsx`
- `frontend/src/pages/StacksPage.tsx:142-149,350-370` — inline double-click destructive confirm, no dialog/focus management.
- `frontend/src/pages/StacksPage.tsx:396` — success banner has no `aria-live`.
- ✓ `:103-105` deploy progress list uses `role="status" aria-live="polite"`.

### `frontend/src/pages/stacks/StackBuilderPage.tsx`
- `frontend/src/pages/stacks/StackBuilderPage.tsx:278` — form prevents default with no submit handler.
- `frontend/src/pages/stacks/StackBuilderPage.tsx:309` — "Loading…" plain text.
- `frontend/src/pages/stacks/StackBuilderPage.tsx:391-397` — no unsaved-changes warning.

### `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/pages/SettingsPage.tsx:193-194` — "Loading GitHub status…" plain text.
- `frontend/src/pages/SettingsPage.tsx:425` — generic "Working…" busy label.
- ✓ `:389-395` avatar has width/height and `alt=""`.

### `frontend/src/pages/AuditLogPage.tsx`
- `frontend/src/pages/AuditLogPage.tsx:95,307` — `toLocaleString([])` instead of explicit `Intl.DateTimeFormat`.
- `frontend/src/pages/AuditLogPage.tsx:159-166` — local-date → UTC drift (also correctness M1).

### `frontend/src/pages/LogsPage.tsx`
- `frontend/src/pages/LogsPage.tsx:294` — `toLocaleString([])`.
- `frontend/src/pages/LogsPage.tsx:132` — export uses un-debounced query (correctness M13).
- ✓ `:187` placeholder ends with `…`, `:249` `autoComplete="off"`, `:285-286` `role="log"` + aria-label.

### `frontend/src/pages/Home.tsx`
- `frontend/src/pages/Home.tsx:22,33-36` — Spanish copy/locale forced `'es'`.

### `frontend/src/components/workloads/WorkloadsTable.tsx`
- `frontend/src/components/workloads/WorkloadsTable.tsx:61-70` — label + `aria-label` duplication.

### `frontend/src/components/Toast.tsx`, `ConfirmDialog.tsx`, `Skeleton.tsx`
- ✓ Toast `:31-32` `role="status" aria-live="polite"` + dismiss `aria-label`; ConfirmDialog `:87-89` dialog semantics, Escape + focus trap + focus restore; Skeletons `aria-hidden` / `aria-busy`.

### `frontend/src/index.css`
- `frontend/src/index.css:468,961,1177,2209` — `:focus` used instead of `:focus-visible` for inputs (all include an outline replacement, so no anti-pattern).
- `frontend/src/index.css:1605` — `outline: none` with background-only focus indicator on combobox options (weak contrast).
- ✓ `:149-153` global `:focus-visible` 2px outline; `:42,122` `color-scheme` dark/light; `:160` `touch-action: manipulation`; `:2444` reduced-motion; `:2802` `overscroll-behavior: contain`; no `transition: all`; no zoom suppression.

### `frontend/src/pages/logs/logs.css`, `frontend/src/pages/audit/audit.css`
- `frontend/src/pages/logs/logs.css:36` — `:focus` not `:focus-visible` (has replacement).
- Responsive filter bars use `flex-wrap` ✓ (`logs.css:8-13`, `audit.css:7-12`).

### `frontend/src/components/charts/MetricChart.tsx`
- `frontend/src/components/charts/MetricChart.tsx:32-45` — hardcoded dark tokens even in light theme (documented AGENTS exception; note for theme QA).
- `:61,115` — `toLocaleString()` with default locale.

---

## 3. Frontend architecture map

### Pages (`frontend/src/pages/`)
| File | Purpose |
|---|---|
| `Home.tsx` | Public landing page; pings `GET /api/health`; Spanish copy. |
| `LoginPage.tsx` | Password login + optional Clerk JS sign-in; `?next=` redirect. |
| `DashboardPage.tsx` | Workload table, resource-usage panel, deployment history, manual refresh. |
| `ContainersPage.tsx` | Main deploy form (image / Git / Dockerfile template), volume uploads, scaling policy, CPU/mem limits, deploy-progress polling, workload actions. |
| `ResourceDashboardPage.tsx` | Per-container CPU/memory/network charts; 1h/6h/24h/7d ranges. |
| `BuilderPage.tsx` | Dockerfile template CRUD. |
| `ImagesPage.tsx` | Dockerfile template CRUD — duplicate of Builder. |
| `LogsPage.tsx` | Log search/filter/pagination, CSV export, live WS log stream. |
| `AuditLogPage.tsx` | Per-user audit timeline with action/target/date filters. |
| `StacksPage.tsx` | Stack cards, deploy/redeploy, build-override recovery, delete. |
| `stacks/StackBuilderPage.tsx` | Create/edit stack services + React Flow dependency graph. |
| `SettingsPage.tsx` | Profile, GitHub OAuth, AI prefill prefs, LLM provider, email alerts. |
| `TeamsPage.tsx` | Projects/teams list, members, invitations, storage quota. |
| `admin/AdminPage.tsx` | User management + global audit tabs (staff/admin guarded). |
| `PlaceholderPage.tsx` | Unused "coming soon" stub. |

### Shared components (`frontend/src/components/`)
`Layout`, `Navbar`, `UserMenu`, `UserAvatar`, `Toast`, `Skeleton`, `ConfirmDialog`, `DockerfileTemplatesSection`, `EmailNotificationSettings`, `VelaMarkIcon`, `VelaSparkIcon`, `useDockerfileTemplates`, `charts/MetricChart`, `workloads/{WorkloadsTable, WorkloadRow, DeployJobRow, ReplicaInstancesPanel, ContainerStatsPanel, ContainerLogPanel, ContainerTerminal}`.

### Hooks
Global: `hooks/useTheme.ts`, `hooks/useActiveDeployJobs.ts`.
Domain: `pages/containers/{useContainerRunForm, useDeploySourceSelection, useGitSourceAnalysis, useImageRefAvailability, useDeployProjects, useWorkloadGroups}`, `pages/teams/useTeamManagement.ts`.

### API client
`frontend/src/api/client.ts` is a pure re-export barrel over `core/`, `containers/`, `deploys/`, `stacks/`, `images/`, `builds/`, `projects/`, `auth/`, `settings/`, `notifications/`, `logs/`, `audit/`, `admin/`, `metrics/`, `scaling/`, `llmErrors.ts`. `core.ts` owns token storage (`vela.access_token`), request dedup + 5-min TTL cache, 401/deactivated handling, `formatApiError`, and WS URL resolution.

### Auth/routing
`main.tsx` → `BrowserRouter` → `AuthProvider` → `App`. `App.tsx` lazy-loads all pages; layout route with `RequireAuth` on every page except `/` and `/login`, plus `RequireStaff` on `/teams` and `/admin`.

---

## 4. Backend endpoints with NO UI surface

Sources: decorators in `backend/app/api/routes/*.py`; frontend wrapper search in `frontend/src/api/`.

| Backend endpoint(s) | Current UI state | User-facing value of exposing |
|---|---|---|
| `POST/GET/DELETE /api/tokens/*` (`tokens.py:21,38,60`) | No API module at all | Personal access tokens let users drive the CLI/CI without embedding a password; core PaaS ergonomics. |
| `GET/POST/DELETE /api/traffic/routes*` (`traffic.py:16,25,43`) | No API module at all | Inspect and manage public HTTP routes independently of deploys; today routes are a side effect of `public_route`. |
| `POST /api/containers/{id}/restart` (`containers.py:1302`) | No client wrapper | A Restart action next to Start/Stop/Remove in the workload row. |
| `GET /api/containers/{id}/health` (`containers.py:1594`) | No client wrapper | Show health-check detail in the row/stats panel instead of a bare health string. |
| `GET/PUT /api/scaling/policies/{container_name}` (`scaling.py:59,82`) | Only the list (`scaling.ts:34`) is used, and only to group replicas | Edit an autoscaling policy on an already-running container; currently only settable at deploy time. |
| `GET /api/metrics/summary` (`metrics.py:98`) | `getMetricSummary` exists at `api/metrics.ts:37` but is never called | Historical CPU/memory aggregates for trend/capacity views. |
| `POST /api/images/pull`, `/api/images/build` (`images.py:45,56`) | No client wrappers; Images page only manages Dockerfile templates | Pull/build images directly from the UI. |
| `GET /api/settings/monitoring/status` (`settings.py:250`) | No client wrapper | Surface collector/alerting health so users know metrics/alerts are active. |
| `GET /api/deployments/{id}` (`deployments.py:37`) | No wrapper (history lists + diffs only) | Full single-deployment detail (snapshot, env, command) from the history row. |
| `GET /api/containers/image/suggestions` (`containers.py:720`) | Wrapper `api/images.ts:39` exists but unused | Expose registry search suggestions in the deploy-source combobox (currently images come from `/deploy-sources`). |

Explicitly **not** gaps: `POST /api/auth/register` is intentionally disabled (`auth.py:85-87`); profile/avatar (`users.py`), GitHub OAuth (`github.py`), audit (`audit.py`), logs (`logs.py`), stacks (`stacks.py`), builder (`builder.py`), admin (`admin.py`) all have UI surfaces.

---

## 5. UX review beyond the guidelines

- **Loading states:** Mostly good skeletons (App lazy fallback `App.tsx:25-33`, teams `Skeleton.tsx:16-84`, logs `LogsPage.tsx:273`, audit `AuditLogPage.tsx:267`, stacks `StacksPage.tsx:405`, metrics `ResourceDashboardPage.tsx:110`). Plain "Loading…" outliers: `StackBuilderPage.tsx:309`, `SettingsPage.tsx:193-194`, `auth/RequireAuth.tsx:16`.
- **Error handling:** Generally follows AGENTS.md — `formatApiError(error)` yields short actionable `detail` strings; inline `role="alert"` in banners. Exceptions: H1 (object `detail` crash), M9 (`'es'` forced on Home), and `formatApiError` falls through to raw `error.message` for non-API errors (`core.ts:149-150`), which can leak low-level text.
- **Empty states:** Good — `StacksPage.tsx:411-420`, `LogsPage.tsx:268-271,311-313`, `AuditLogPage.tsx:322-326`, `TeamsPage.tsx:112-113`, `ResourceDashboardPage.tsx:116-122`, `WorkloadsTable` (`hasContent` at `:118`).
- **Destructive confirmations:** `ConfirmDialog` used in Containers (`ContainersPage.tsx:348`), Dashboard (`:138`), Teams (`:148,166`), Settings (`:218`), StackBuilder (`:421`). Outliers: **M2** stack delete inline confirm; Dockerfile template delete in `DockerfileTemplatesSection` should be checked (no dialog visible in Images/Builder wiring).
- **Form ergonomics:** Stack name form (**M12**), inputs missing `name` (**L1**), no unsaved-changes guards (**M3**), inline field errors good in `useContainerRunForm`/StackBuilder.
- **Navigation/hierarchy:** Navbar links role-aware (`Navbar.tsx:23-27`) ✓; account-menu buttons (**M5**); tab state not deep-linked (**M15**); no skip link (**H3**).
- **Responsive:** Filter bars wrap (`logs.css:8`, `audit.css:7`); breakpoints at 640/720/768px. Workload tables are wide with no horizontal-scroll wrapper noted — verify on small screens.
- **Dark/light theme:** Tokens + `color-scheme` correct (`index.css:42,103-123`); pre-paint theme script good. Gaps: theme-color (**M8**), chart/xterm hardcoded dark (documented exception), Spanish copy unrelated.
- **Accessibility:** Strong baseline (aria-labels on icon buttons, `aria-expanded`/`aria-controls` in workload rows, focus trap in dialogs, `role="log"`/`role="status"`). Gaps: H3, M4, M5, L4, L11, M11.
- **Consistency:** Images/Builder duplication (**M14**); `containers-page__title` class reused as page H1 in Images/Builder/Stacks/StackBuilder rather than page-specific classes; confirm-dialog vs inline-confirm split.

---

## 6. Correctness bugs

- **H1** non-string API `detail` → render crash. `api/core.ts:157`.
- **M1** audit date TZ drift. `AuditLogPage.tsx:159-166`.
- **M13** export uses wrong search value. `LogsPage.tsx:132`.
- **L2** `//` next path. `LoginPage.tsx:9-10`.
- **L6** uncleaned highlight timers. `StackBuilderPage.tsx:185,368`.
- **L7** render-phase ref write. `ContainersPage.tsx:126`.
- **L8** terminal dispose leak on early return. `ContainerTerminal.tsx:27,31-39`.
- **L9** localStorage write can throw. `useTheme.ts:23`.
- **L14** stale deployment history. `DashboardPage.tsx:22,119`.
- WebSocket lifecycle itself is correct: both `ContainerLogPanel.tsx:145-156` and `ContainerTerminal.tsx:55-62` null handlers, cancel rAF, disconnect observers and close sockets on unmount. Route guards (`RequireAuth`, `RequireStaff`) and 401/account-deactivated session teardown (`core.ts:104-116`, `AuthProvider.tsx:54-77`) are correct.

---

## 7. Over-engineering / code quality

- Dedup + TTL cache + session generation in `core.ts:10-14,225-272` is custom machinery for a small app; pragmatic but adds a second caching layer on top of browser HTTP caching (L16).
- `api/client.ts` (268 lines) is a pure re-export barrel — every import takes an extra hop (L16).
- Duplicated Images/Builder stack (M14); dead code (L15); oversized files (L16); JSDoc noise (L17).
- `ponytail:` comments document deliberate tradeoffs (1s deploy polls, structural graph compare, id fallback) — acceptable, but the triple poll loop (M6) deserves consolidation.

---

## 8. Documentation drift (frontend-specific)

- **M10** `README.md:272` — "Most specs ... work entirely against mocked HTTP responses installed via `page.route(...)` ... no Postgres or Docker is required" is false; `frontend/e2e/` has zero `page.route` calls and `frontend/playwright.config.ts:97-120` boots real API + Vite with SQLite. `AGENTS.md` also explicitly forbids `page.route` for app flows.
- `README.md:263` says Playwright starts both servers "on the test ports" — accurate, but it does not document `PW_API_PORT` / `PW_VITE_PORT` overrides (`playwright.config.ts:12-13`), nor that `reuseExistingServer: false` requires freeing 8000/5173 (`AGENTS.md` does).
- `README.md:274-278` (venv auto-detect, `PW_API_SERVER_COMMAND`) matches `playwright.config.ts:27-42` ✓; `README.md:285-288` commands match `frontend/package.json:12-14` ✓.
