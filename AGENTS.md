# Agent rules (Vela)

Conventions for tooling, dependencies, naming, and Python style. Follow this file when changing the repo.

## Commands

```powershell
# Backend
cd backend
python -m pytest tests -q                                    # all tests
python -m pytest tests/test_auth.py -q                       # single file
python -m pytest tests/test_auth.py::test_register -q        # single test
ruff check .                                                  # lint
mypy app/ tests/                                              # typecheck
alembic upgrade head                                          # DB migrations

# Frontend
cd frontend
npm run dev                                                   # dev server (Vite proxy → :8000)
npm run build                                                 # tsc -b && vite build
npm run lint                                                  # eslint .
npm run typecheck                                             # tsc -b
npm run test:e2e                                              # Playwright suite
npm run test:e2e -- e2e/auth.spec.ts                          # single spec
npm run test:e2e -- -g "Settings page"                        # filter by name
npm run test:e2e:headed                                       # headed (watch browser)
PW_API_SERVER_COMMAND="..." npm run test:e2e                   # custom API command
```

## CI environment

Not using these env vars locally will cause test failures or wait on Docker:

```powershell
$env:VELA_FAKE_ORCHESTRATOR = "1"       # replaces DockerOrchestrator with in-memory fake
$env:VELA_DATABASE_URL = "sqlite+aiosqlite:///:memory:"   # no Postgres needed for pytest
```

CI runs pytest for `backend/` and Playwright for `frontend/` (with `VELA_E2E=1` SQLite via `playwright.config.ts`). No Docker or Postgres needed for tests.

The E2E suite resets the database on API startup (`app/e2e_support.py` `ensure_e2e_database`). Most specs stub `/api/**` with `page.route`; only `api.spec.ts` hits the live backend.

## Db / engine quirks

- **Runtime** uses `postgresql+asyncpg`. **Alembic** uses `postgresql+psycopg` (sync) because `asyncpg` + `asyncio` fails on some Windows + Docker Desktop setups.
- On Windows, `localhost` → `127.0.0.1` is mapped automatically in `app/db/engine.py` (`_database_url_for_engine`).
- `VELA_DATABASE_URL` for async is `postgresql+asyncpg://user:pass@host:port/db`. For Alembic the driver is swapped to `psycopg`.
- `sqlalchemy.engine.url.URL` masks passwords in `str()` — use `render_as_string(hide_password=False)` when constructing live connection strings.
- Test conftest overrides: `integration_app` (DB + orchestrator + builder + router + storage), `db_app` (DB only), `api_client` (authed), `make_authed_client` (per-test override builder).

## Package management (npm)

- `frontend/.npmrc` sets `save-exact=true`. New dependencies must be pinned — no `^` / `~` in `package.json`.
- Project uses **npm** (not pnpm). Lockfile: `package-lock.json`.

## Backend structure (MVC)

- **Model** (`app/core/`): Domain logic, orchestration, integrations. No HTTP wiring.
- **View** (`app/api/schemas.py`, route-local models): Request/response shapes.
- **Controller** (`app/api/routes/*`, `app.py`, `deps.py`): Thin HTTP handlers — parse input, call core, map errors to HTTP, return view models.

Group `app/core/` modules into `app/core/<domain>/` when >=3 modules. Existing domains: `auth/`, `oauth/`, `security/`, `traffic/`, `containers/`, `build/`, `git/`, `deploy/`, `notifications/`.

Entrypoint: `run.py` (imports `app.bootstrap_env` for `.env`), module target `app.api.app:app` for uvicorn.

A background `asyncio.Task` (`container_monitor.py`) runs via FastAPI lifespan. Tests that call `create_app()` may need to account for it.

## Backend testing

- Prefer **real wiring** over mocks. Integration tests with `TestClient`, real app factory, and in-memory SQLite are the default.
- Avoid replacing orchestrators/builders/auth with `MagicMock` unless external services are genuinely unavailable in CI.
- Assert on HTTP responses and persisted state, not mock call counts.

## Frontend testing

- E2E tests (`frontend/e2e/`) run the real frontend against the real local API. Do not stub `/api/**` for flows you are verifying.
- Reserve `page.route` for external systems the app cannot control in dev (third-party OAuth, etc.). Document why.

## TypeScript / React

- Avoid `instanceof` — prefer discriminated unions, `typeof`/`in`, type predicates, or Zod.
- Keep page files readable; split subviews/hooks/shared UI when a file grows hard to scan.
- Prefer deriving state during render or event handlers over `useEffect`. Reserve effects for real side effects.
- API client in `frontend/src/api/client.ts`: token in `localStorage` key `vela.access_token`, helpers `apiGet`/`apiPost`/`apiPatch`/`apiDelete`/`apiUploadFile`.
- Containers run form (`ContainersPage.tsx`): always sends `public_route: true`, user-selected `container_port` (default 80), no host port mapping, shows Git branch only when source looks like a Git URL.

## Errors shown to users

- Surface client-facing messages, not raw implementation details or stack traces.
- Backend: structured HTTP errors (`detail`) from domain exceptions. Map unexpected failures to a safe generic message.
- Frontend: short actionable string from API `detail` or mapped message.
