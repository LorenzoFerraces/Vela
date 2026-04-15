# Vela

Local development stack: **FastAPI backend** (Docker orchestration + optional Traefik file routes), **Vite/React frontend**, and **Traefik** as an optional edge proxy.

## Prerequisites

- [Python](https://www.python.org/downloads/) **3.12+** and `pip`
- [Node.js](https://nodejs.org/) **20+** (project uses **npm**; see [frontend/README.md](frontend/README.md))
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine) running
- [Git for Windows](https://git-scm.com/download/win) if you use Git URLs for builds

## Repository layout

| Path | Role |
|------|------|
| [backend/](backend/) | FastAPI app, `run.py`, [backend/.env.example](backend/.env.example) |
| [frontend/](frontend/) | Vite UI (`npm run dev`) |

## 1. Backend API

From the repository root (or any directory; adjust paths if you prefer always `cd backend`).

### Install

```powershell
cd C:\Users\lolo\Vela\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Environment

Copy the example env file and edit it:

```powershell
Copy-Item .env.example .env
```

Important variables for local dev:

| Variable | Purpose |
|----------|---------|
| `VELA_TRAFFIC_ROUTER` | `noop` (default), `traefik_file`, or `kubernetes` (scaffold only) |
| `VELA_TRAEFIK_DYNAMIC_FILE` | **Absolute path** to a **JSON file** Vela writes for Traefik (required when `traefik_file`) |
| `VELA_DOCKER_NETWORK` | Optional. User-defined **Docker network name** (e.g. `vela-net`) attached to **every** new Vela container so Traefik can reach them by name |
| `VELA_PUBLIC_ROUTE_DOMAIN` | Optional. Base domain for **generated** hostnames when the UI/API sends `public_route: true` (e.g. `apps.example.com`). Point **wildcard DNS** `*.apps.example.com` at your public Traefik (or LB). |
| `VELA_PUBLIC_URL_SCHEME` | `https` (default) or `http`. Drives Traefik TLS on the generated router and the `public_url` returned by the API. |
| `VELA_PUBLIC_ROUTE_HOST_PREFIX` | Optional. First label prefix before the random segment (default `vela-`). |

`backend/.env` is loaded automatically when the API starts ([backend/app/bootstrap_env.py](backend/app/bootstrap_env.py)). See [backend/.env.example](backend/.env.example) for a template.

### Public URLs (customers, no manual hosts)

When **`VELA_PUBLIC_ROUTE_DOMAIN`** is set, clients can pass **`public_route: true`** on **POST `/api/containers/run`** (or **`public_route`** on **POST `/api/containers/deploy`**). Vela ignores client-supplied `route_host`, allocates a unique name under that domain, wires Traefik like today, and returns **`public_url`** in the JSON response. Your edge must already serve that domain (wildcard DNS + TLS). **POST `/api/containers/deploy`** returns **`container`**, **`route_wired`**, and **`public_url`** (not a bare `ContainerInfo`).

### Run the API

```powershell
cd C:\Users\lolo\Vela\backend
.\.venv\Scripts\Activate.ps1
python run.py
```

The dev server listens on **http://127.0.0.1:8000** by default.

Health check:

```powershell
curl http://127.0.0.1:8000/api/health
```

## 2. Traefik (optional, for hostname routes from the UI)

Traefik must read a **single JSON file** (not a directory). If that path does not exist as a file before the container starts, Docker may create a **directory** with that name and Traefik will error with `is a directory`.

### Create the dynamic config file (once)

Pick a path (example uses your profile folder to avoid permission issues):

```powershell
$traefikDir = "$env:USERPROFILE\vela-traefik"
New-Item -ItemType Directory -Force -Path $traefikDir | Out-Null
Set-Content -Path "$traefikDir\vela-http.json" -Encoding utf8 -Value '{}'
```

Set in `backend/.env` (use the **same** network name as Traefik’s `--network`, created above):

```env
VELA_TRAFFIC_ROUTER=traefik_file
VELA_TRAEFIK_DYNAMIC_FILE=C:\Users\<YourUser>\vela-traefik\vela-http.json
VELA_DOCKER_NETWORK=vela-net
```

Use the **same** host path in the Docker `-v` mount below (forward slashes are fine: `C:/Users/...`).

### Start Traefik (Docker)

```powershell
docker network create vela-net 2>$null

docker run -d --name traefik --restart unless-stopped `
  --network vela-net `
  -p 80:80 `
  -p 8080:8080 `
  -p 443:443 `
  -v "C:/Users/<YourUser>/vela-traefik/traefik-http.json:/etc/traefik/dynamic/traefik-http.json" `
  traefik:v3.2 `
  --providers.file.filename=/etc/traefik/dynamic/traefik-http.json `
  --providers.file.watch=true `
  --entrypoints.web.address=:80 `
  --entrypoints.websecure.address=:443 `
  --api.dashboard=true `
  --api.insecure=true
```

#### HTTPS (`VELA_PUBLIC_URL_SCHEME=https` and `https://` public URLs)

Browsers open **`https://`** on **port 443**. The minimal Traefik command above only exposes **`web` on :80**, so **`https://` will time out** until you add TLS on 443.

1. Map **443**: e.g. `-p 443:443` on the Traefik container.
2. Add **`websecure`**: e.g. `--entrypoints.websecure.address=:443`.
3. Configure **certificates** for your hostnames (wildcard `*.your.ddns.net` or ACME). See [Traefik HTTPS / TLS](https://doc.traefik.io/traefik/https/tls/).
4. Forward **443** from your home/office router to the machine running Traefik.

When a route has TLS enabled, Vela registers **two** Traefik routers for the same host: **`web`** (:80) and **`websecure`** (:443), so both **`http://`** and **`https://`** reach the container. The **`websecure`** router carries **`tls: {}`** (use your default cert, files, or ACME). Until 443 + certs exist, keep **`VELA_PUBLIC_URL_SCHEME=http`** and use **`http://`** URLs on port **80** only.

- **Dashboard:** http://127.0.0.1:8080/dashboard/ (insecure; fine for local dev only).
- With **`VELA_DOCKER_NETWORK=vela-net`**, Vela attaches new workload containers to that network at create time, so Traefik can resolve `http://<container_name>:<port>` without manual `docker network connect`.

### Browsers without editing `hosts`

Vela does **not** auto-edit the system hosts file: that needs administrator rights, triggers UAC on Windows, and varies by OS.

Use a hostname that already resolves to your machine:

| Pattern | Example | Notes |
|---------|---------|--------|
| **`*.localhost`** | `http://myapp.localhost/` | Modern browsers/OSes treat subdomains of `localhost` as loopback, so **no hosts file** for local HTTP testing. |
| **nip.io** (and similar) | `http://myapp.127.0.0.1.nip.io/` | Public DNS returns **127.0.0.1**; put the **exact** name in the UI “Traefik hostname” field so the `Host()` rule matches. |

Custom names like `app.test` still need **`127.0.0.1 app.test`** in hosts (or `curl --resolve app.test:80:127.0.0.1 http://app.test/`).

## 3. Frontend

```powershell
cd C:\Users\lolo\Vela\frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173** (or the URL Vite prints).

If the API is not on port 8000, create `frontend/.env.local`:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## 4. Typical startup order

1. Start **Docker Desktop**.
2. Create **`vela-http.json`** as a real file; set **`VELA_TRAEFIK_DYNAMIC_FILE`** in `backend/.env`.
3. Start **Traefik** (`docker run` … above).
4. Start **backend** (`python run.py` from `backend/`).
5. Start **frontend** (`npm run dev` from `frontend/`).

## 5. Useful commands

| Action | Command |
|--------|---------|
| Backend tests | `cd backend` → `python -m pytest tests -q` |
| Frontend production build | `cd frontend` → `npm run build` |
| Stop Traefik | `docker stop traefik` |
| Traefik logs | `docker logs -f traefik` |

## 6. Troubleshooting

| Issue | What to check |
|-------|----------------|
| `is a directory` for Traefik JSON | Host path must be a **file**; remove a wrongly created folder and recreate the file (section 2). |
| `Access denied` writing under repo `resources/` | Use a path under `%USERPROFILE%` or fix folder vs file (section 2). |
| API cannot reach Docker | Docker Desktop running; engine healthy. |
| UI cannot reach API | `VITE_API_BASE_URL`, CORS (API allows localhost:5173), backend running on 8000. |
| Traefik 502 to app | Set **`VELA_DOCKER_NETWORK`** to Traefik’s network; correct **container name** and **port** in the generated route. |
| `routers cannot be a standalone element` (file provider) | Traefik rejects **empty** `http.routers` / `http.services` maps. Use **`{}`** as the initial file content (see section 2), or upgrade Vela so it omits those keys when there are no routes. |

For more detail on the Traefik file integration, see the traffic router code under [backend/app/core/](backend/app/core/).
