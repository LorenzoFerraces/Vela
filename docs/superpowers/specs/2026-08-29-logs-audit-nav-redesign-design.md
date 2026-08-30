# Design: De-noise top bar, relocate Logs/Audit, restyle both pages

Date: 2026-08-29
Status: Approved (placement: user menu; restyle scope: bigger redesign)

## Problem

- The top bar has 8 flat links (Dashboard, Containers, Stacks, Builder, Teams, Logs,
  Audit Log, Settings) in `frontend/src/components/Navbar.tsx`. It is noisy and
  horizontally scrolls on narrow viewports (`.navbar__nav` uses `overflow-x: auto`,
  no breakpoints).
- **Logs** (`/logs`) is a DB-backed *history* browser (7-day retention, `ContainerLog`
  table). Its natural entry point is already the per-container "Logs" button in the
  workloads table (`WorkloadsTable.tsx:332-340`, links to `/logs?container_id=<id>`,
  used on Containers and Dashboard pages). The top-bar link is redundant.
- **Audit Log** (`/audit`) is a per-user, low-frequency action history, reachable
  only from the top bar.
- Both pages' look is disliked: plain list layouts, free-text container-ID input on
  Logs, raw action strings + never-shown `details` JSON on Audit.

## Goals

1. Remove **Logs** and **Audit Log** from the top bar; keep 5 primary app links.
2. Relocate account-scoped items (Settings, Audit Log, Log out) into a user menu
   dropdown triggered by the avatar/name cluster.
3. Redesign both pages (terminal-style Logs viewer, timeline-style Audit log) with
   the filters the backends already support but the UI never exposed.
4. Frontend-only change: **zero backend changes** — all needed query params already
   exist (`start_time`/`end_time`, `source` on `/api/logs/`; `from_date`/`to_date`
   on `/api/audit/log`; `listContainers()` at `client.ts:559`).

## Non-goals

- Live log tailing on the Logs page (the in-row `ContainerLogPanel` already provides
  live WebSocket tailing for running containers).
- Log virtualization (page size is 100 rows — not needed).
- Admin/system area, multi-user audit views, `/images` nav placement.
- Any backend/API change.

## Decisions

### 1. Navigation: user menu

- New component `frontend/src/components/UserMenu.tsx`.
- The current avatar + display-name + "Log out" button cluster becomes:
  avatar + name as a single trigger button (`aria-haspopup="menu"`,
  `aria-expanded`), plus a dropdown with `role="menu"`, items `role="menuitem"`:
  - **Settings** → `/settings` (gear icon)
  - **Audit Log** → `/audit` (clock/list icon)
  - divider
  - **Log out** (log-out icon)
- Phosphor icons, `aria-hidden="true"` on decorative icons (repo standard).
- A11y behavior follows the repo modal model: close on Escape and outside click,
  restore focus to the trigger, keyboard reachable (items are `<button>`).
- `Navbar.tsx` `navItems` reduces to: Dashboard, Containers, Stacks, Builder, Teams.
  The `navigation[aria-label="Main"]` landmark and `navbar__link--active` styling are
  kept. The standalone "Log out" ghost button is removed from the bar.
- Routes unchanged: `/logs` and `/audit` stay as full pages behind `RequireAuth`.
  `/logs` remains reachable from the workloads-table "Logs" button (URL param
  pre-selection).
- New CSS lives in the existing navbar block in `index.css` (navbar styles are
  already there; no new file for the menu chrome) — menu items reuse `btn`/`navbar__link`
  tokens.

### 2. Logs page redesign (`/logs`, `LogsPage.tsx`)

- **Container picker**: replace the free-text "Container ID…" input with a `<select>`
  populated from `listContainers()` (options show container name + status).
  The `container_id` URL param remains the source of truth; the workloads-table
  links still pre-select a container. Without a selection: friendly empty state
  ("Select a container to view logs"), no request fired (matches the backend's
  required `container_id`).
- **Filter bar** (all persisted to URL search params, `replace: true`):
  - container select (`container_id`)
  - level select: All / info / warn / error / debug (`level`)
  - date range: two native `<input type="datetime-local">` mapped to `start_time` /
    `end_time` (ISO for the API)
  - free-text search (`q`)
  - **Export CSV** button (existing `exportLogs`), disabled until a container is set
- **Terminal-style viewer**: dark monospace panel matching the existing
  container-terminal visual language. Each row: dim timestamp, level badge using
  the existing log-level color tokens, source, message in `pre-wrap` monospace.
  Longest-line wrapping, no horizontal scroll.
- Kept: offset pagination (100/page, Prev/Next), 5-row skeleton,
  `containers-banner--err` error banner, stale-response seq guard, "Showing X of Y"
  count.
- CSS moves out of `index.css` into a new `frontend/src/pages/logs/logs.css`
  imported by the page (per AGENTS.md: don't grow index.css).
- Backend endpoints unchanged: `GET /api/logs/`, `GET /api/logs/export`
  (`backend/app/api/routes/logs.py`).

### 3. Audit page redesign (`/audit`, `AuditLogPage.tsx`)

- **Timeline layout**: entries grouped by day within the current page (Today,
  Yesterday, then `Mon d, yyyy` headers). Each entry: Phosphor icon per action,
  human-readable sentence (e.g. "Deployed container `abc1234567`"), target
  (type + short id), localized time. `details` JSON expandable per row
  (native `<details>` with pretty-printed JSON).
- **Fix data gaps in the UI**: add the missing `container.exec` label to
  `ACTION_LABELS`; surface `details` (currently fetched but never displayed).
- **Filter bar** (URL params, `replace: true`):
  - action select (from `ACTION_LABELS`, incl. new `container.exec`)
  - target select: All / Containers / Users (`target_type`)
  - date range: two native `<input type="date">` mapped to `from_date` / `to_date`;
    date-only values are expanded client-side — `from_date` → `T00:00:00`,
    `to_date` → `T23:59:59` (backend takes ISO datetimes)
- Kept: offset pagination (50/page, Prev/Next), skeleton, error banner, race guard,
  "Showing X of Y" count. Per-user scoping is enforced server-side — unchanged.
- CSS moves out of `index.css` into a new `frontend/src/pages/audit/audit.css`.
- Backend endpoint unchanged: `GET /api/audit/log` (`backend/app/api/routes/audit.py`).

### 4. Tests

- `frontend/e2e/smoke.spec.ts`:
  - Walk list becomes all 5 top-bar links (Dashboard, Containers, Stacks, Builder,
    Teams): click each, assert URL; assert h1 where the page has one (verify during
    implementation; fall back to URL-only assertion for any page without an h1).
  - Assert Logs and Audit Log are **not** in the `navigation[Main]` landmark.
  - Add a walk: open the user menu (avatar/name button) → click **Settings** →
    assert `/settings` URL.
  - Logout test: the "Log out" control is now a `menuitem` inside the opened menu;
    update `getByRole('button', { name: 'Log out' })` accordingly.
- `frontend/e2e/logs.spec.ts`:
  - Container-ID text input becomes a container `<select>`; update the load test
    (select a seeded E2E container, assert rows render).
  - The "enter `nonexistent-id` → Container not found" case is replaced by two
    cases: (a) no container selected → friendly empty state, no request fired;
    (b) URL opened with an unknown `container_id` param (direct navigation) →
    error banner still renders.
- `frontend/e2e/audit` — none exists; add one small spec: page loads via the user
  menu (menu → Audit Log), heading + empty/seeded state render, action filter present.
- Backend pytest suite untouched (no backend changes).

## Affected files

| File | Change |
|---|---|
| `frontend/src/components/UserMenu.tsx` | New — dropdown menu component |
| `frontend/src/components/Navbar.tsx` | 5 nav items; render `<UserMenu/>`; drop Log out button |
| `frontend/src/pages/LogsPage.tsx` | Redesign: picker, date range, terminal viewer |
| `frontend/src/pages/logs/logs.css` | New — moved + restyled page CSS |
| `frontend/src/pages/AuditLogPage.tsx` | Redesign: timeline, exec label, details, date range |
| `frontend/src/pages/audit/audit.css` | New — moved + restyled page CSS |
| `frontend/src/index.css` | Remove `.logs-page__*` / `.audit-log-page__*` blocks; add user-menu styles |
| `frontend/src/api/client.ts` | No endpoint changes; verify `LogQueryParams`/`AuditLogQueryParams` already carry date fields (they do) |
| `frontend/e2e/smoke.spec.ts` | Menu-driven Settings/Log out; nav assertions |
| `frontend/e2e/logs.spec.ts` | Picker-based assertions |
| `frontend/e2e/audit.spec.ts` | New small spec |

## Verification

- `cd frontend && npm run lint` and `npm run build` (tsc).
- `cd backend && python -m pytest tests -q` (must stay green — no backend changes).
- `cd frontend && npm run test:e2e` full Playwright suite (API on 8000, Vite on 5173,
  `FakeContainerOrchestrator`, seeded E2E users).

## Open questions

None — placement (user menu) and scope (bigger redesign) approved by the user
on 2026-08-29.
