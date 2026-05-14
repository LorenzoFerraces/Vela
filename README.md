# Vela

FastAPI backend, Vite/React frontend, optional Traefik as an edge proxy, and PostgreSQL for users and related data.

## Prerequisites

- Python **3.12+** and `pip`
- Node.js **20+** and **npm**
- Docker Desktop (or Docker Engine)
- **PostgreSQL 16+** (or use the repo’s Docker Compose file for a local instance)
- Git (if you build from Git URLs)

## Layout

| Path | Role |
|------|------|
| `backend/` | API (`python run.py`) |
| `backend/alembic/` | Database migrations (Alembic) |
| `frontend/` | UI (`npm run dev`) |
| `docker-compose.dev.yml` | Optional local Postgres for development |

## Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Database (PostgreSQL)

Point `VELA_DATABASE_URL` in `backend/.env` at a running Postgres instance. Example URL shape:

`postgresql+asyncpg://USER:PASSWORD@HOST:15432/DATABASE`

To start Postgres locally with Docker:

```powershell
docker compose -f docker-compose.dev.yml up -d
```

`docker-compose.dev.yml` maps **host port 15432** to **container port 5432** (Postgres’s default inside the image), so it does not use **5432** or **5433** on your machine. Use **`127.0.0.1:15432`** in `VELA_DATABASE_URL`, with user/password/database matching `POSTGRES_*` in that file (defaults: `vela` / `vela` / `Vela`).

**`FATAL: password authentication failed for user "vela"`** — if `VELA_DATABASE_URL` matches compose, check that connection code does not use `str(sqlalchemy.engine.url.URL)` for live DSNs: SQLAlchemy **2.x masks passwords as `***` in `str(URL)`**, so drivers would send the wrong password. This repo’s `app/db/engine.py` uses `render_as_string(hide_password=False)` when rewriting the URL. Separately, a **stale Postgres data volume** from older `POSTGRES_*` values can cause real auth failures; the compose volume name `vela_postgres_dev_data` avoids reusing an old init, or run `docker compose -f docker-compose.dev.yml down -v` then `up -d`.

Then apply the schema:

```powershell
cd backend
alembic upgrade head
```

Alembic uses the **sync** driver `postgresql+psycopg` (see `sync_database_url_for_alembic` in `app/db/engine.py`) because `asyncpg` + `asyncio` often fails on **Windows** with Docker-hosted Postgres even when `psql` works. The API runtime still uses **`postgresql+asyncpg`** in `VELA_DATABASE_URL`.

### Environment variables

Create `backend/.env` as needed. Common variables:

| Variable | Notes |
|----------|--------|
| `VELA_DATABASE_URL` | Async SQLAlchemy URL (e.g. `postgresql+asyncpg://vela:vela@127.0.0.1:15432/Vela` when using this repo’s Compose port) |
| `VELA_AUTH_SECRET` | Long random secret used to sign JWT access tokens |
| `VELA_AUTH_ACCESS_TOKEN_TTL_MINUTES` | Optional; access token lifetime in minutes (default sensible if omitted) |
| `VELA_TRAFFIC_ROUTER` | `noop` (default), `traefik_file`, or `kubernetes` |
| `VELA_TRAEFIK_DYNAMIC_FILE` | Absolute path to the JSON file Traefik loads (if using `traefik_file`) |
| `VELA_TRAEFIK_RELOAD_CONTAINER` | Optional Docker **container name** (as in `docker ps`) for Traefik; after each route write, Vela sends **SIGHUP** so Traefik reloads the file when fsnotify misses changes (typical on Docker Desktop) |
| `VELA_DOCKER_NETWORK` | Docker network name so Traefik can reach workload containers |
| `VELA_PUBLIC_ROUTE_DOMAIN` | Base domain for generated public hostnames (optional) |
| `VELA_PUBLIC_URL_SCHEME` | `https` or `http` for public URLs |
| `VELA_ALLOWED_BUILD_ROOT` | Restricts local build paths on the server (optional) |
| `VELA_FRONTEND_BASE_URL` | Used by the GitHub OAuth callback to redirect the browser back to the SPA after success/error (e.g. `http://localhost:5173`) |
| `VELA_GITHUB_CLIENT_ID` / `VELA_GITHUB_CLIENT_SECRET` | OAuth App credentials for GitHub. Register at [github.com/settings/developers](https://github.com/settings/developers); the App's **Authorization callback URL** must equal `VELA_GITHUB_OAUTH_REDIRECT_URI` |
| `VELA_GITHUB_OAUTH_REDIRECT_URI` | Public URL of `GET /api/auth/github/callback`, e.g. `http://localhost:8000/api/auth/github/callback` |
| `VELA_GITHUB_OAUTH_SCOPES` | Comma-separated scopes requested from GitHub (default `repo,read:user`) |
| `VELA_TOKEN_ENCRYPTION_KEY` | Fernet key used to encrypt third-party access tokens at rest. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

```powershell
python run.py
```

API: **http://127.0.0.1:8000** — health: `GET /api/health` (no auth).

### Authentication

- `POST /api/auth/register` — create an account; returns `{ access_token, token_type, user }`.
- `POST /api/auth/login` — email + password; same response shape.
- `GET /api/auth/me` — current user; requires `Authorization: Bearer <access_token>`.

Most **`/api/containers/**`** routes require that bearer token. Containers are scoped per user (Docker label `vela.owner_id`).

### GitHub integration (private repos)

To deploy private GitHub repos, connect a GitHub account from the **Settings** page in the UI. The flow is a standard OAuth App authorization:

- `GET /api/auth/github/start` — returns the GitHub authorize URL (the SPA navigates to it).
- `GET /api/auth/github/callback` — GitHub redirects here with `?code&state`; the API exchanges the code, encrypts the access token (Fernet, key from `VELA_TOKEN_ENCRYPTION_KEY`), and stores it in `user_oauth_identities`. The browser is then sent back to `${VELA_FRONTEND_BASE_URL}/settings?github=connected` (or `?github=error&reason=...`).
- `GET /api/auth/github/status` — `{ connected, login?, avatar_url?, scopes?, connected_at? }` (never returns the token).
- `DELETE /api/auth/github` — disconnects the account and removes the stored token.
- `GET /api/github/repos` and `/api/github/repos/{owner}/{repo}/branches` — back the **Pick from GitHub** picker on Containers.

When you `POST /api/containers/run` with a private `github.com` URL, the server transparently uses the connected user's stored token to clone (passed via `git -c http.extraheader=...` so the token never appears in URLs or process listings).

## Traefik (optional)

Use a **single JSON file** for dynamic config (not a directory). Point `VELA_TRAEFIK_DYNAMIC_FILE` at it and set `VELA_TRAFFIC_ROUTER=traefik_file`. Put Traefik and app containers on the same Docker network (`VELA_DOCKER_NETWORK`). Set **`VELA_TRAEFIK_RELOAD_CONTAINER`** to your Traefik container name so the API can signal Traefik to reload after each change (file watches often fail on Docker Desktop bind mounts; Traefik reloads dynamic file config on SIGHUP). See [Traefik docs](https://doc.traefik.io/traefik/) for TLS and entrypoints.

## Frontend

```powershell
cd frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. Override the API base URL in `frontend/.env.local` if needed:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

**Sign-in:** use **Register** (`/register`) or **Log in** (`/login`). After a successful register or login, the UI stores the access token in **localStorage** under `vela.access_token` and sends it on API requests. Protected app routes redirect to `/login` when you are not signed in.

## Useful commands

| Action | Command |
|--------|---------|
| Backend tests | `cd backend` → `python -m pytest tests -q` |
| DB migrations (apply) | `cd backend` → `alembic upgrade head` |
| Frontend build | `cd frontend` → `npm run build` |
| Frontend e2e tests | `cd frontend` → `npm run test:e2e` |

## End-to-end tests (Playwright)

The `frontend/e2e/` suite drives the SPA in a real browser against a real FastAPI process. Playwright's `webServer` config starts both the API (`python -m uvicorn app.api.app:app`) and Vite dev server on the test ports automatically.

```powershell
cd frontend
npm ci
npx playwright install --with-deps chromium
npm run test:e2e
```

Most specs (auth, settings, dashboard, containers) work entirely against mocked HTTP responses installed via `page.route(...)` — the only test that actually hits the live backend is `e2e/api.spec.ts` (`GET /api/health`). That means **no Postgres or Docker is required to run the suite**.

**Python interpreter selection.** Playwright auto-detects the repo's virtualenv: if `<repoRoot>/.venv/Scripts/python.exe` (Windows) or `<repoRoot>/.venv/bin/python` (Unix) exists, it is used to launch uvicorn. So after the standard `Backend` setup above (which creates `.venv` and installs `pip install -e ".[dev]"`), `npm run test:e2e` works without further configuration. If neither is found, plain `python` on `PATH` is used. To force a specific interpreter, set `PW_API_SERVER_COMMAND`, e.g.:

```powershell
$env:PW_API_SERVER_COMMAND = "C:\path\to\python.exe -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000"
npm run test:e2e
```

Useful variants:

| Command | What it does |
|---------|--------------|
| `npm run test:e2e -- e2e/auth.spec.ts` | Run a single spec |
| `npm run test:e2e -- -g "Settings page"` | Filter by test name |
| `npm run test:e2e:headed` | Watch the browser |
| `npm run test:e2e:ui` | Open the Playwright UI runner |

The CI workflow (`.github/workflows/e2e.yml`) installs Python + Node + Chromium and runs the full suite on every push and pull request that touches `frontend/` or `backend/`.

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| Traefik JSON `is a directory` | Path must be a file, not a folder |
| Traefik hot reload / stale routes | Set **`VELA_TRAEFIK_RELOAD_CONTAINER`** to the Traefik container name. Also prefer **mounting the parent directory** for the dynamic file; ensure `providers.file.watch` is true. |
| API vs Docker | Docker running; socket reachable |
| UI vs API | `VITE_API_BASE_URL`; backend on port 8000; CORS |
| `401` on container or image routes | Register or log in; ensure requests send `Authorization: Bearer …` (the UI does this when a token is stored) |
| Database connection errors | Postgres is running; `VELA_DATABASE_URL` matches your instance; run **`alembic upgrade head`** from `backend/` |
| `WinError 64` / `ConnectionDoesNotExistError` from the **API** (asyncpg) on Windows | Docker Desktop / `localhost` / timing: prefer **`127.0.0.1`** in `VELA_DATABASE_URL` (the app maps `localhost` → `127.0.0.1` on Windows). `alembic upgrade` uses **sync psycopg** and is usually unaffected. |
| `FATAL: password authentication failed` for user `vela` | `VELA_DATABASE_URL` must match **`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`** and the **published host port** in `docker-compose.dev.yml` (currently **15432**). If you changed those env vars **after** the first `up`, remove the volume and recreate: `docker compose -f docker-compose.dev.yml down -v` then `up -d`. Compose must map **`15432:5432`** (host:container), not `HOST:HOST`. |
