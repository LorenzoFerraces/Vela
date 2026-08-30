# Agent rules (Vela)

Conventions for tooling, dependencies, naming, and Python style. Follow this file when changing the repo.

## Repo management

- **Keep the readme concise** when adding or updating the readme file.

## Package management (pnpm / npm)

- **Exact versions only** in `package.json` — no `^` or `~`. `frontend/.npmrc` sets `save-exact=true`. After adding a dependency, verify the entry has no range prefix.

## Backend setup

- **Virtualenv**: create at the **repo root** (`python -m venv .venv`), not inside `backend/`. Playwright's `webServer` resolves `<repoRoot>/.venv/Scripts/python.exe` to launch uvicorn.
- **Install**: `pip install -e ".[dev]"` from `backend/`.
- **Run**: `python run.py` from `backend/` (uvicorn on port 8000, reload on).
- **Env file**: `backend/.env` — see README for full variable list.

### Database

- Local Postgres via `docker compose -f docker-compose.dev.yml up -d` (host port **15432** → container 5432).
- `VELA_DATABASE_URL` uses `postgresql+asyncpg` for the API runtime.
- Alembic uses **sync psycopg** (`sync_database_url_for_alembic` in `app/db/engine.py`) — do not change this.
- Apply migrations: `alembic upgrade head` from `backend/`.

### Key env vars

| Variable | Purpose |
|----------|---------|
| `VELA_FAKE_ORCHESTRATOR=1` | Swaps real Docker for `FakeContainerOrchestrator` (tests, E2E) |
| `VELA_E2E=1` | Enables E2E mode: seeds users, mocks GitHub, allows DB reset |
| `VELA_E2E_ALLOW_DB_RESET=1` | Required alongside `VELA_E2E` to permit schema drop+create |
| `VELA_TRAFFIC_ROUTER` | `noop` (default), `traefik_file`, or `kubernetes` |
| `VELA_OBJECT_STORAGE` | `memory` (default for dev/tests) or `r2` |

## Backend structure (MVC)

Under `backend/app/`:

- **Model** (`app/core/`): Domain logic, orchestration, integrations. No HTTP wiring.
- **View** (`app/api/schemas.py`): Request/response shapes and serialization.
- **Controller** (`app/api/routes/`, `app.py`, `deps.py`): Thin HTTP handlers.

### `app/core/` domain packages

Group modules under `app/core/<domain>/` when the domain has **3+** Python modules. Smaller areas stay flat at `app/core/` root.

Existing domains: `auth/`, `oauth/`, `security/`, `traffic/`, `containers/`, `build/`, `git/`, `deploy/`, `notifications/`, `profile/`, `storage/`, `projects/`, `scaling/`.

## Backend testing

- **Pytest**: `cd backend && python -m pytest tests -q`
- **conftest.py** wires real routes with `TestClient`, in-memory SQLite, and `FakeContainerOrchestrator` — no Docker required.
- Fixtures: `api_client` (authenticated), `other_user_client`, `anonymous_client`, `integration_app`, `db_app`.
- **Prefer real wiring** over mocks. Unit tests only for isolated pure logic. Integration tests are the default for API behavior.
- For safety-critical paths (auth, ownership, deploy), assert on HTTP responses and persisted state, not mock calls.

## Frontend

- **Dev server**: `cd frontend && npm run dev` (Vite on port 5173).
- **Build**: `npm run build` (runs `tsc -b && vite build`).
- **Lint**: `npm run lint`.
- Override API URL in `frontend/.env.local`: `VITE_API_BASE_URL=http://127.0.0.1:8000`.
- Auth token stored in `localStorage` under `vela.access_token`.

## Frontend E2E tests (Playwright)

- **Run**: `cd frontend && npm run test:e2e`
- **Single spec**: `npm run test:e2e -- e2e/auth.spec.ts`
- **Headed**: `npm run test:e2e:headed`
- **UI runner**: `npm run test:e2e:ui`

The suite drives the real SPA against the real FastAPI process. Playwright `webServer` starts both on **separate ports** (API: 8000, Vite: 5173 — the `e2eApiPort` / `e2eVitePort` defaults in `frontend/playwright.config.ts`, overridable via `PW_API_PORT` / `PW_VITE_PORT`). `reuseExistingServer` is off, so stop any dev server on those ports before running. The API uses SQLite at `backend/e2e-playwright.db` and `FakeContainerOrchestrator`.

**No `page.route` mocking** for app flows — tests hit the live backend with seeded E2E users. The only direct API test is `e2e/api.spec.ts` (`GET /api/health`). Reserve network interception for external systems only (e.g., OAuth redirects).

E2E user credentials in `frontend/e2e/constants.ts` must stay in sync with `backend/app/e2e_support.py`.

## Variable and identifier naming

- Use **clear, full words** (`container_id`, `request_body`). Avoid cryptic abbreviations and single-letter names except idiomatic local loop indices.

## Python style

- Idiomatic Python: explicit, typed where helpful, `match`/`case` for exhaustiveness on unions. Match surrounding modules for layout and error handling.

## Cleaning AI-generated changes (deslop)

After substantive agent-generated edits on a branch, run the **deslop** Cursor skill on the diff: remove unnecessary comments, abnormal defensive `try`/`except` on trusted paths, `any` casts used only to silence types, and deeply nested structure that does not match surrounding code — **without changing behavior** except for clear bugs. Prefer small, focused cleanups over broad rewrites.

## TypeScript / React (frontend)

- **Avoid `instanceof` when practical.** Prefer discriminated unions, narrow with `typeof` / `in`, small type-predicate helpers, or parsing/validation (e.g. Zod) so behavior does not depend on prototype chains or cross-realm objects.
- Use `instanceof` only where it is clearly the best tool (e.g. a well-owned `Error` subclass in the same bundle) and document why if it is non-obvious.
- **Keep page and component files from growing too large.** Split out subviews, hooks, and shared UI into focused modules when a file becomes hard to scan or review.
- **Reuse across pages** when the same UI or logic appears in more than one place — extract shared components or hooks rather than duplicating large blocks.
- **`useEffect`**: Prefer deriving state during render, event handlers, or library patterns that avoid sync-on-mount when they suffice. Reserve effects for real side effects (subscriptions, imperative DOM, syncing with external systems) and avoid redundant or overly chained effects that are hard to reason about.

## UI and forms (user experience)

- **Prioritize user experience** when designing and building interfaces: flows should feel clear, fast, and respectful of attention.
- **Follow common UX patterns** where they apply: clear navigation and hierarchy, visible loading and success/error feedback, sensible empty states, destructive actions behind confirmation, keyboard-friendly controls where the rest of the app does the same. Stay consistent with existing pages in this repo before introducing a new interaction model.
- **Loading states**: Prefer **skeleton placeholders** that mirror the final layout over blank screens or generic “Loading…” text. Keep structure stable so the page feels responsive. Use **optimistic UI** when it is safe (update local state immediately, reconcile on success or roll back with a clear error on failure) so actions feel instant.
- **When usability or user flow is unclear** (e.g. multi-step flows, dense data, unfamiliar domain), ask for product or design guidance or propose **short** options in chat instead of guessing a one-off pattern.
- **Keep form fields short and concise** (labels, placeholders, helper text). Prefer tight copy over verbose prose.
- **Avoid long explanations** inline on the form; if something needs detail, link to docs or a collapsible help pattern rather than wall-of-text above fields.
- **Long forms are fine to split**: use **multi-step flows** or **modals** (and related patterns) so users are not overwhelmed by a single scrolling page of inputs.
- **Containers** (`frontend/src/pages/ContainersPage.tsx`): the run form always uses **public routes** (`public_route: true`), a user-selected **container port** (defaults to 80; Git analysis may pre-fill when enabled in settings), no host port mapping, and shows **Git branch** only when the source looks like a Git URL (same `git@` / `http(s)://` / `ssh://` prefix rules as `POST /api/containers/run` on the server).

## UI standards (frontend)

Verified against the ui-ux-pro-max skill; the codebase already follows these — keep it that way.

- **Design tokens**: `frontend/src/index.css` `:root` is the single source of color truth. Two themes ship: dark (default, `:root`) and light (`[data-theme='light']` override on `<html>`) — the purple tactical palette, visual reference in `docs/design/palette-examples.html`. Theme toggle: `src/hooks/useTheme.ts` + navbar button, persisted in `localStorage` under `vela.theme`, applied pre-paint by the inline script in `index.html`. No raw hex/rgba in components or inline styles — the only exceptions are library props that cannot consume CSS variables (xyflow in `StackVisualizer.tsx`, xterm theme in `ContainerTerminal.tsx`, log-level colors in `LogsPage.tsx`); keep those hex values in sync with the dark theme tokens.
- **Brutalist rules**: 0 border-radius everywhere; flat surfaces (no gradients or drop shadows — CRT scanline/noise overlays and zero-offset status-dot glows excepted); JetBrains Mono base type with Archivo Black for macro titles; uppercase + wide tracking for micro type; `[ BRACKET ]` page titles. Terminal green `--status-live` is reserved for `running` status readouts only.
- **Contrast**: body text ≥ 4.5:1 against its background. Current tokens pass; check any new token before use.
- **Focus**: never remove a focus outline without a visible replacement. Inputs use `outline: none` + accent border + `box-shadow` ring; buttons/links use `:focus-visible` with a 2px `--accent` outline.
- **Icons** (Phosphor): decorative icons beside visible text get `aria-hidden="true"`; icon-only buttons get an `aria-label` (plus `aria-expanded`/`aria-pressed` where stateful).
- **Status feedback**: errors use `role="alert"`; non-urgent updates use `role="status"` / `aria-live="polite"`; banners use the existing `*-banner--err` / `--ok` classes.
- **Modals**: `role="dialog"` + `aria-labelledby`, close on Escape, restore focus to the trigger (pattern in `BuildConfigModal.tsx`).
- **Forms**: every field has a visible `<label htmlFor>`; errors appear near the field, not only in a top banner.
- **Motion**: keep animations inside/compatible with the existing `prefers-reduced-motion: reduce` block in `index.css`.
- **CSS organization**: global styles live in `index.css` (already 3000+ lines). Put new page-specific styles in a separate CSS file imported by that page — do not grow `index.css`.
- **Design/UX decisions**: consult the ui-ux-pro-max skill (searchable local guidance) before choosing styles, colors, or interaction patterns.

## Errors shown to users (frontend and API)

- **Surface client-facing messages**, not raw implementation details. Do not let low-level or library errors reach the UI unchanged when a clearer explanation is possible.
- **Frontend**: On failure, show a short, actionable string (e.g. from API `detail` or a mapped message). Avoid re-throwing or logging-only flows that leave the user with a generic “Something went wrong” or a stack trace in production UI.
- **Backend**: Prefer structured HTTP errors (`detail`, optional fields) from domain exceptions; avoid leaking stack traces or internal identifiers in normal error responses. Map unexpected failures to a safe generic message when appropriate.

## Verification

- **Always run both backend and E2E tests after substantive changes** before claiming work is complete. Run `python -m pytest` in `backend/` and the Playwright E2E suite in `frontend/e2e/`. Do not skip verification—tests are the only check that persists after the session ends.
After substantive agent edits, clean the diff: remove unnecessary comments, abnormal `try`/`except` on trusted paths, `any` casts only to silence types, and deeply nested structure that doesn't match surrounding code — **without changing behavior** except for clear bugs.
