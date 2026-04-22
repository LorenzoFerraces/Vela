# Vela

FastAPI backend, Vite/React frontend, and optional Traefik as an edge proxy.

## Prerequisites

- Python **3.12+** and `pip`
- Node.js **20+** and **npm**
- Docker Desktop (or Docker Engine)
- Git (if you build from Git URLs)

## Layout

| Path | Role |
|------|------|
| `backend/` | API (`python run.py`) |
| `frontend/` | UI (`npm run dev`) |

## Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Create `backend/.env` as needed. Common variables:

| Variable | Notes |
|----------|--------|
| `VELA_TRAFFIC_ROUTER` | `noop` (default), `traefik_file`, or `kubernetes` |
| `VELA_TRAEFIK_DYNAMIC_FILE` | Absolute path to the JSON file Traefik loads (if using `traefik_file`) |
| `VELA_TRAEFIK_RELOAD_CONTAINER` | Optional Docker **container name** (as in `docker ps`) for Traefik; after each route write, Vela sends **SIGHUP** so Traefik reloads the file when fsnotify misses changes (typical on Docker Desktop) |
| `VELA_DOCKER_NETWORK` | Docker network name so Traefik can reach workload containers |
| `VELA_PUBLIC_ROUTE_DOMAIN` | Base domain for generated public hostnames (optional) |
| `VELA_PUBLIC_URL_SCHEME` | `https` or `http` for public URLs |
| `VELA_ALLOWED_BUILD_ROOT` | Restricts local build paths on the server (optional) |

```powershell
python run.py
```

API: **http://127.0.0.1:8000** — health: `GET /api/health`

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

## Useful commands

| Action | Command |
|--------|---------|
| Backend tests | `cd backend` → `python -m pytest tests -q` |
| Frontend build | `cd frontend` → `npm run build` |

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| Traefik JSON `is a directory` | Path must be a file, not a folder |
| Traefik hot reload / stale routes | Set **`VELA_TRAEFIK_RELOAD_CONTAINER`** to the Traefik container name. Also prefer **mounting the parent directory** for the dynamic file; ensure `providers.file.watch` is true. |
| API vs Docker | Docker running; socket reachable |
| UI vs API | `VITE_API_BASE_URL`; backend on port 8000; CORS |
