# Backend review — Vela (`fix/security-and-cli-hardening`)

Scope: `backend/` (all of `app/`, `alembic/`, `tests/`), plus root `docker-compose.yml`, `.env.example`, `traefik/static/spa.yaml`, `README.md`. Current checkout treated as code under review, including uncommitted edits to README/.env/docker-compose. Line numbers are from this checkout.

---

## 1. Architecture map (read from code, not inferred)

### 1.1 API route modules — `backend/app/api/routes/`

| Module | Mounted at (`app.py`) | What it actually does |
|---|---|---|
| `containers.py` (1605 lines) | `/api/containers` | Container list/get/deploy/run (async 202), start/stop/restart/remove, logs (HTTP + WS stream), interactive exec WS, stats, health, image availability/suggestions, deploy-source suggestions, volume-folder upload. Ownership via `require_container_access` → project membership from Docker labels. |
| `projects.py` | `/api/projects` | Personal/shared project CRUD, invitations (create/list/accept/reject/cancel), member role update/remove/leave, storage-quota read/update. Instructor-gated member/invitation routes. |
| `settings.py` | `/api/settings` | AI prefill prefs, BYO LLM provider get/set/delete/test, email notification prefs + alert history, monitoring status. |
| `stacks.py` | `/api/stacks` | Stack CRUD, compose/manifest parse, LLM repo analysis, async stack deploy (202), composition cycle detection. |
| `auth.py` | `/api/auth` | `/config` (Clerk availability), `/register` (always 403), `/login` (password + in-process rate limit), `/clerk/exchange`, `/me`. |
| `github.py` | `/api/auth` + `/api/github` (two routers) | GitHub OAuth start/callback/status/disconnect; repo + branch proxy using the user's encrypted token. |
| `admin.py` | `/api/admin` | Admin user list/patch, global audit; instructor-only user creation. |
| `users.py` | `/api/users` | Self profile patch, avatar upload/delete via object storage. |
| `tokens.py` | `/api/tokens` | PAT create (JWT-only), list, revoke. |
| `deployments.py` | `/api/deployments` | Deployment history list/get/diff, scoped to caller. |
| `deploys.py` | `/api/deploys` | `GET /active` — poll async deploy jobs for accessible projects. |
| `logs.py` | `/api/logs` | Persisted container-log query + CSV export (container access checked). |
| `metrics.py` | `/api/metrics` | Stored metric points, hourly summary, per-project usage. |
| `scaling.py` | `/api/scaling` | Scaling policy list/get/put for accessible containers. |
| `audit.py` | `/api/audit` | Caller's own audit entries with filters. |
| `traffic.py` | `/api` (no extra prefix) | `GET/POST /routes`, `GET/DELETE /routes/{id}` — **no authentication** (see F1). |
| `images.py` | `/api/images` | Local image list, pull, build from server path — **no authentication** (F2). |
| `builder.py` | `/api/builder` | Build from source/local path, analyze local path (**no auth**), analyze Git source (auth). |
| `dockerfile_templates.py` | `/api/dockerfiles` | Per-user Dockerfile template CRUD. |

95 route decorators total (19 route modules). Health: `GET /api/health` unauthenticated.

### 1.2 Domain packages — `backend/app/core/`

`auth/` (JWT, bcrypt-SHA256 passwords, PATs, bootstrap admin, roles), `oauth/` (Clerk JWT/JWKS verification, GitHub OAuth state/identity/token encryption), `projects/` (roles OWNER/OPERATOR/VIEWER, membership/invitations, personal workspace bootstrap), `containers/` (abstract `ContainerOrchestrator`, `DockerOrchestrator` with Docker SDK, `FakeContainerOrchestrator` for tests/E2E, volume uploads, test_run), `build/` (git clone → Dockerfile bootstrap → `docker build`, registry suggestions), `git/` (shallow clone via subprocess, language detection, dependency evidence, Dockerfile templates, LLM repo analysis), `llm/` (provider registry: Gemini/Vertex/OpenAI-compatible/Anthropic; Fernet-encrypted per-user keys; commit-keyed SQLite cache), `stacks/` (compose/k8s manifest parsers, repo analysis, deploy topology), `deploy/` (async job registry, GitHub token injection, history), `traffic/` (no-op, Traefik file writer, Kubernetes stub), `scaling/` (CPU-based engine + policies), `notifications/` (health monitor, Brevo email alerts), `monitoring/` (metric collector), `logging/` (log collector + level inference), `quotas/` (team storage quota), `audit/`, `admin/`, `profile/`, `security/` (Fernet secrets, outbound URL SSRF guard).

### 1.3 DB models — `backend/app/db/models.py`

`User` (role string `admin|instructor|student`, `personal_project_id`), `UserOAuthIdentity` (provider + encrypted token, unique per provider/subject and provider/user), `UserLlmProvider` (encrypted BYO key), `Dockerfile`, `Organization`, `Project` (`storage_quota_bytes`, `is_personal`), `ProjectMembership`, `ProjectInvitation`, `DeploymentRecord` (env values redacted in history), `EmailPreference`, `ScalingPolicy`, `AlertHistory`, `AuditLog`, `ContainerLog`, `Stack`, `StackService`, `StackComposition`, `ContainerMetric`, `ApiToken` (no expiry/scope/last-used columns).

### 1.4 Background services/jobs — started in `app/api/app.py:45-124` lifespan

- `DeployJobRegistry` (in-memory, event-loop only) — `app.py:65-66`, `core/deploy/jobs.py`.
- `run_monitoring_loop` (container health/alert emails) — `app.py:68`, `core/notifications/container_monitor.py`.
- `run_metrics_collector` (Docker stats → `container_metrics`) — `app.py:79`, `core/monitoring/metrics_collector.py`.
- `run_scaling_loop` — `app.py:88-90`, `core/scaling/scaling_engine.py`.
- `LogCollector` (stdout/stderr → `container_logs`) — `app.py:92-103`, `core/logging/collector.py`.
- Bootstrap: `ensure_e2e_database` (`app.py:57`) and `ensure_admin_user` (`app.py:59-60`).
- Startup skips metrics/scaling/log loops gracefully when Docker/Traefik is unavailable (`app.py:72-103`).

---

## 2. Features actually implemented

Password login (registration disabled) + optional Clerk passwordless exchange; GitHub OAuth for private repos; JWT + PAT auth with three platform roles; personal workspaces and team projects with viewer/operator/owner RBAC and invitations; per-team storage quotas; container deploy from image / Git URL / saved Dockerfile template via async jobs with phase polling; container lifecycle (start/stop/restart/remove), live logs and interactive exec WebSockets, stats/health; read-only folder volume uploads; object-storage avatars (memory or Cloudflare R2); Dockerfile template library; image pull/build; Traefik file-provider public routes with auto-allocated hostnames; Kubernetes router scaffold; CPU-based auto-scaling with replicas; stack (compose/K8s manifest) import, analysis and deploy; persisted metrics, logs, audit trail and alert emails; BYO LLM provider (Gemini/Vertex/OpenAI-compatible/Anthropic) for repo pre-fill with commit-keyed cache; CLI-facing PAT endpoints.

---

## 3. Findings by severity

### CRITICAL

**F1 — `GET/POST/DELETE /api/routes` are completely unauthenticated.**
`backend/app/api/routes/traffic.py:13` is `router = APIRouter()` with **no `dependencies=`**, and none of the four handlers (`traffic.py:16,25,34,43`) declares `Depends(get_current_user)`. `app.py:228-232` mounts it directly at `/api`.

```python
@router.post("/routes", response_model=RouteInfo)
async def upsert_route(
    spec: RouteSpec,
    traffic_router: Annotated[TrafficRouter, Depends(get_traffic_router)],
) -> RouteInfo:
    """Create or replace a route."""
    return await traffic_router.upsert_route(spec)
```

Any anonymous caller can enumerate all public hostnames, **create/replace arbitrary Traefik routes** (pointing at any backend reachable from the edge, e.g. `vela-api:8000`, `vela-postgres:5432`), and **delete every route** (global outage of all public apps). The whole traffic control plane is exposed. No test file covers this module.

**F2 — `/api/images/*` is unauthenticated and exposes arbitrary server-side Docker operations.**
`backend/app/api/routes/images.py:33` `router = APIRouter()` with no auth; `images.py:36` (`GET /`), `:45` (`POST /pull`), `:56` (`POST /build`). An anonymous caller can list all local image tags, pull arbitrary images (disk exhaustion), and build images from **any existing directory on the API host** — `validate_local_build_context` (`core/build/default_image_builder.py:23-38`) only restricts the path when `VELA_ALLOWED_BUILD_ROOT` is set, and `.env.example:213` leaves it empty by default. `core/git/project_analysis.py:35-84` (`ensure_dockerfile_for_build`) writes a generated `Dockerfile` into that directory before building, so this is also an **unauthenticated arbitrary-file-write primitive** plus a `docker build` DoS.

**F3 — `POST /api/builder/build` and `/analyze` are unauthenticated.**
`backend/app/api/routes/builder.py:24` `router = APIRouter()`; `builder.py:27-37` (`/build`) and `:40-47` (`/analyze`) lack `Depends(get_current_user)` (only `/analyze-source` at `:50-56` has it). `BuilderBuildRequest` accepts `ProjectSource` with `local_path` (`core/models.py:242-255`), routing through the same unrestricted `validate_local_build_context` → `ensure_dockerfile_for_build` → `docker build` as F2. Also allows anonymous Git clones of arbitrary URLs (SSRF/resource abuse).

**F4 — Traefik rule injection via backticks in `path_prefix` (cross-tenant traffic hijack).**
`core/traffic/traefik_file_traffic_router.py:48-50`:

```python
def _path_rule(path_prefix: str) -> str:
    escaped = path_prefix.replace("\\", "\\\\").replace("'", "\\'")
    return f"PathPrefix(`{escaped}`)"
```

Backticks are **not** escaped/rejected (unlike `_host_rule` at `:42-45`, which rejects `` ` ``). `RouteSpec.path_prefix` (`core/traffic/traffic_models.py:52-56,71-77`) and `RunFromSourceRequest.route_path_prefix` (`api/schemas.py:137-143,225-243`) allow arbitrary strings up to 512 chars starting with `/`. A crafted prefix closes the backtick-quoted Traefik string and appends extra matchers (e.g. `Host(...)`), letting a user make their router match hostnames belonging to other tenants/the SPA and route that traffic to their own container. Amplified by F1 (no auth needed).

### HIGH

**F5 — A project VIEWER can destroy stack workloads; Docker side effects happen before the write-authorization check.**
`api/routes/stacks.py:233-272` (`DELETE /api/stacks/{id}`): `get_stack()` (only checks *membership*, `core/stacks/repository.py:55-77`) is used at `:240`; then `:244-268` unconditionally stops/removes every matching container and the stack network; only **afterwards** does `:270` call `delete_stack()`, which performs the `can_write` check (`core/stacks/repository.py:152-168`). A viewer therefore gets a 403 after their stack's containers and network are already gone (DB rollback cannot undo Docker mutations). `PUT /stack` and `POST /stack/{id}/deploy` do check write access correctly (`stacks.py:367-372`, `repository.py:99-118`), making this an outlier.

**F6 — Scaled replicas silently lose the base container's runtime configuration.**
`core/scaling/scaling_engine.py:145-152` builds the replica config from `ContainerInfo` fields only:

```python
base_config = DeployConfig(
    image=base_info.image,
    name=base_name,
    container_listen_port=base_port,
    labels=dict(base_info.labels),
    volumes=list(base_info.volumes),
    health_check=default_listen_port_health_check(base_port),
)
```

`ContainerInfo` has no `env_vars`, `command`, `cpu_limit`, `memory_limit`, `network` or `restart_policy`, so replicas start without DB URLs/API keys/start commands and without resource limits. Scale-out workloads will typically crash-loop or behave differently from the primary.

**F7 — Unbounded in-memory reads before size limits on file uploads (memory-exhaustion DoS).**
`api/routes/containers.py:823-844`: the early check uses client-declared `upload.size`, then `content = await upload.read()` (`:831`) reads the whole file before `total_bytes` is checked (`:833`). A forged small `size`/no size with a multi-GB body is fully materialized in RAM. Same pattern for avatars: `api/routes/users.py:57` `body = await file.read()` before `validate_avatar_bytes` enforces 2 MB (`core/profile/service.py:86-96`).

### MEDIUM

**F8 — Login throttling is weak and easy to make global.** `api/routes/auth.py:41-59,98-102`: per-process `defaultdict(deque)` keyed on `request.client.host`; 10 attempts/5 min. Compose sets `FORWARDED_ALLOW_IPS` (`docker-compose.yml:76`) so XFF is honored *in compose*, but any deployment behind a proxy without that var buckets every user under the proxy IP (one attacker locks out all users). No throttle at all on `/auth/clerk/exchange` (`auth.py:107-147`), PAT creation or password reset. In-memory state is lost on restart and meaningless with multiple workers. Explicitly acknowledged by the `ponytail:` comment at `auth.py:41-42`.

**F9 — Platform `instructor` role can manage membership of *any* project.** `api/routes/projects.py:296-338` (patch/delete member) and `:355-417` (invitations) gate on `require_instructor`; `core/projects/repository.py:118-132` `_require_project_manager` lets `can_manage_users()` (admin OR instructor) bypass project ownership. Instructors can add arbitrary users as operators/remove non-owner members of personal and team projects they do not own. README documents "instructor: manage teams" (`README.md:130`), so this may be intended, but it is a broad cross-tenant capability with no audit emission on these routes.

**F10 — Git clone URL allowlist permits internal/private network targets (SSRF/probe).** `core/git/git_ops.py:15-27`: `_ALLOWED_SCHEMES = ("https://", "http://", "ssh://", "git://", "git@")`; no host/IP validation (contrast the LLM-specific `validate_outbound_url` in `core/security/outbound_url.py`). A user can trigger server-side connections to `http://127.0.0.1:*`, link-local metadata, or LAN hosts through `/api/run`, `/api/builder/build`, `/api/stacks/analyze-repo`, leaking reachability via `CloneError` messages. `git` itself is invoked with an argv list (no shell), so command injection is not present.

**F11 — Personal access tokens never expire and have no scopes/usage tracking.** `db/models.py:667-692` (`ApiToken`: only id/user/name/prefix/hash/created_at); `core/auth/api_tokens.py:27-68`. A leaked PAT is valid until manually revoked (`api/routes/tokens.py:60-77`). No expiry, last-used timestamp, IP binding or scope separation — a CLI PAT grants the full rights of its owner, including container exec and project mutation.

**F12 — Clerk exchange auto-provisions accounts purely from an email claim.** `api/routes/auth.py:120-147`: any token verified by the configured Clerk instance with an unknown email creates a new user (`STUDENT`) and personal workspace; if the email matches an existing account, that account is logged in. Security rests entirely on the external Clerk org's invitation policy (comment at `:127-128`), and `VELA_ALLOWED_ORIGINS`/`azp` enforcement is optional with only a warning (`core/oauth/clerk.py:110-124,250-253`). Wrong-tenant Clerk configuration = account takeover/provisioning for anyone in that instance.

**F13 — Live log-stream WebSockets have no cap or session lifetime.** `api/routes/containers.py:1373-1424`: `stream_logs` acquires the `VELA_MAX_LOG_STREAMS` semaphore *inside the orchestrator* (`docker_orchestrator.py:880-944`) but there is no per-session timeout (the exec WS has `_exec_max_session_seconds()` at `containers.py:1555`), no idle detection, and `websocket.accept()` happens before auth (`:1385` vs `:1398`). An authenticated user can pin Docker follow-streams and a thread per connection indefinitely.

**F14 — Hardcoded personal DDNS domain is shipped as the default in three places.** `api/app.py:193-194` (CORS `http(s)://velaunq.ddns.net:5173`), `.env.example:87` (`VELA_DOMAIN=velaunq.ddns.net`), `docker-compose.yml:117` (same default). The CORS `allow_origin_regex` (`app.py:196`) also allows any `http(s)://localhost:<port>` with `allow_credentials=True`. Vendor-specific strings in a self-hosted product are a config footgun and can unintendedly authorize an external origin.

**F15 — JWTs have no issuer/audience binding.** `core/auth/tokens.py:51-91`: only `sub/iat/exp/type`; `decode_access_token` verifies signature/expiry/type. Fine for a single app, but a token signed with the shared `VELA_AUTH_SECRET` is accepted by every Vela service (the same secret also signs GitHub OAuth state, `core/oauth/state.py:36-56`) — no audience separation between auth purposes.

**F16 — `Dockerfile` generation writes into the build context and is reachable from unauthenticated paths.** `core/git/project_analysis.py:59-84` computes `target = effective_root / dockerfile_name` and writes generated content there; combined with F2/F3 this is unauthenticated file creation on the API host. `build_subdir` from the request is constrained by `core/git/project_analysis.py:22-32` (`is_relative_to(root)`), which limits traversal but not the parent-context restriction.

**F17 — Deployment history `env_vars` are redacted to keys only, which breaks the diff/rollback value.** `api/routes/containers.py:379-384` stores `{"KEY": "<REDACTED>"}` for every env var; `api/routes/deployments.py:51-66` exposes a diff. That is the right security choice, but there is no secret-reference/secret-store feature, so users cannot see or restore previous configuration — the history is mostly metadata. (Security-correct, product-incomplete.)

**F18 — LLM result cache is global and shared across users/providers.** `core/llm/cache.py:19-23,26-31`: SQLite key is `(kind, version, commit_sha)` with no user id, provider key or repo URL (only `endpoint_fingerprint` exists in `core/llm/provider.py:34-42`, and it is not part of the cache key). Two users analysing the same commit of a private repo can share one cached analysis; changing provider does not invalidate. `VELA_LLM_CACHE_DIR` is not documented in `.env.example`.

### LOW / QUALITY

**F19 — Dead duplicate code in the Docker orchestrator.** `core/containers/docker_orchestrator.py:145-176` repeats the "permission denied" and "no such file" branches verbatim; `:603-604` calls `self._ensure_default_network_sync()` twice; `:667-673` duplicates the entire `except docker.errors.NotFound` block (with unreachable statements). No behavior change, pure noise.

**F20 — Dead auth code after registration was disabled.** `api/routes/auth.py:80-87` always raises `RegistrationDisabledError`, but `core/auth/service.py:24-37` `register_user`, `api/schemas.py` `RegisterRequest` (`~:691`) and the `EmailAlreadyRegisteredError` handler remain wired. README correctly documents the 403 (`README.md:137`).

**F21 — Duplicate constant.** `core/llm/provider.py:7` and `:12` both define `DEFAULT_LLM_MODEL` (first `gemini-3.5-flash-lite`, second `gemini-3.1-flash-lite`); the second wins. README (`:103`) says `gemini-3.1-flash-lite`, `.env.example:139` says `gemini-2.0-flash` — three different documented defaults.

**F22 — Fragile path-prefix containment check.** `core/containers/volume_uploads.py:164-176`: `if not str(root).startswith(str(user_root))` is a string-prefix check rather than `Path.is_relative_to`; safe today only because `upload_id`/`user_id` are typed UUIDs. There is also no `DELETE` endpoint for volume uploads, so users cannot reclaim the 150 MB quota.

**F23 — Upload quota check is non-atomic.** `core/containers/volume_uploads.py:106-118` and `api/routes/containers.py:817-844` compute usage then write; concurrent uploads can exceed both per-user and team quotas.

**F24 — Code-style typo.** `api/routes/containers.py:825` comment ends with a stray backslash: `# Only read content if early size check passes\`.

**F25 — Stack network names are global but derived only from the stack name.** `core/stacks/repository.py:120-121`: `network_name = f"vela-stack-{sha256(name)[:12]}"` with a global unique constraint (`db/models.py:570`). Two teams cannot use the same stack name, despite uniqueness being intended per project (`db/models.py:557-559`).

**F26 — `scaling.py` authorizes policy writes with a read-level check.** `api/routes/scaling.py:24-40,82-97` `_require_accessible_container_name` only verifies the container appears in the caller's list; `PUT /policies/{name}` is a write operation but a VIEWER can call it. (Also `scaling_policies.container_name` is globally unique, so an accessible name is enough.)

**F27 — Unauthenticated paths emit no audit events.** `emit_audit_log` is called for container deploy/lifecycle/exec/profile actions, but not for traffic route changes, image pull/build, PAT creation/revocation, or stack deletion's Docker side effects. With F1-F3 anonymous, there is no attribution at all for the highest-risk operations.

---

## 4. Missing / incomplete features (with user-facing value)

1. **Kubernetes traffic router is a non-functional scaffold.** `core/traffic/kubernetes_traffic_router.py:15-33` raises `"Kubernetes traffic router is not implemented yet"` from every method, yet `VELA_TRAFFIC_ROUTER=kubernetes` is advertised in README (`:90`) and `.env.example:69`. *Value: teams deploying to k8s would get working ingress instead of startup failures.*
2. **RPS-based auto-scaling is fake.** `core/scaling/scaling_engine.py:53-56` maps `REQUESTS_PER_SECOND` to CPU with a TODO. *Value: traffic-driven scaling actually responds to load.*
3. **No way to update an existing container's config** (env, image tag, resources, command). Only create/start/stop/restart/remove exist (`containers.py:1254-1354`). *Value: roll out a new image or fix env vars without delete+recreate downtime.*
4. **No deploy rollback / one-click "redeploy previous version."** History and diff exist (`deployments.py`) but cannot be applied. *Value: recover from a bad deploy immediately.*
5. **No volume-upload deletion/management endpoint** (`api/routes/containers.py` only has POST `/volume-uploads`). *Value: users can free their 150 MB quota without deleting containers.*
6. **No CI/webhook trigger for Git deploys** — deploys are user-initiated only. *Value: push-to-deploy pipelines.*
7. **No secret store / env-var reference type** — secrets are only supplied inline and redacted in history (F17). *Value: share deploy configs without exposing credentials.*
8. **Deploy job state is in-memory and dies with the process** (`core/deploy/jobs.py:1-9,83-199`; documented). *Value: job status survives API restarts and works with multiple workers.*
9. **No per-user/per-team container-count or CPU quota** (only storage quotas). *Value: prevent a single tenant from exhausting the shared Docker host.*
10. **Login/clerk/token endpoints lack per-account lockout and audit events** (F8, F27). *Value: detect and stop credential attacks.*

---

## 5. Over-engineering / complexity to simplify

- **Unused-by-default auth surface:** `register_user` + `RegisterRequest` + registration error mapping (F20) can be deleted outright.
- **Three competing LLM default-model declarations** (F21) collapse to one.
- **Duplicated orchestrator error-handling and double network-ensure call** (F19) are copy/paste leftovers; remove them.
- **`FakeContainerOrchestrator` is 536 lines** mirroring most of the real 1310-line orchestrator; acceptable for E2E but a candidate for a single shared behavior-test suite instead of parallel implementations.
- **`core/logging/inference.py` (23 lines) and many one-line wrapper modules** (`core/quotas/__init__.py` re-exports, `core/security/__init__.py`) add indirection without behavior; acceptable but lean toward direct imports.
- **Local build paths and image/build endpoints duplicate the builder pipeline** (`images.py` vs `builder.py`); both call `validate_local_build_context` + `ensure_dockerfile_for_build` + `build_image`. One shared service would remove the authentication gap too (F2/F3).

---

## 6. Test coverage gaps

Tests exist and are substantial for auth (`test_auth.py`, `test_clerk_jwt.py`, `test_clerk_exchange.py`, `test_api_tokens.py`, `test_admin_users.py`), projects/RBAC (`test_projects_api.py`, `test_rbac_teams.py`), LLM (`test_llm_*.py`, 8+ files), scaling engine, log/metric collectors + APIs, storage quota, stacks (parse/analysis/permissions), Docker orchestrator internals, deploy jobs, and audit.

**No test module at all for the route files with the worst auth defects:** `traffic.py`, `images.py`, `builder.py` (only `test_ensure_dockerfile.py` covers the helper), `logs.py`, `containers.py` (only `test_exec_websocket.py` covers one WS path), `deployments.py`, and `deploys.py`. This is a direct explanation for F1-F3 surviving review.

Also missing: negative authorization tests for viewer-vs-operator/owner on stack delete (F5) and scaling policy write (F26); tests that the CORS/HSTS middleware sees error responses exist (`test_app_middleware.py`) but no test asserts auth on every mounted router.

---

## 7. Documentation drift

- `README.md:156`: "Containers are scoped per user (Docker label `vela.owner_id`)" — actual code is project-membership-based via `vela.project_id` with `owner_id` fallback (`core/projects/access.py:19-74`, `docker_orchestrator.py:799-840`).
- `README.md:261-272`: claims most Playwright specs use `page.route(...)` mocking and "no Postgres or Docker is required." `AGENTS.md` explicitly forbids this and `frontend/playwright.config.ts` runs live API + Vite with `VELA_E2E=1`/SQLite seeded users. The README is wrong about the current suite.
- `README.md:241-245,135-145` documents only password login; the Clerk endpoints (`GET /api/auth/config`, `POST /api/auth/clerk/exchange`) and `VELA_CLERK_*` behavior (`.env.example:105-113`) are undocumented.
- `README.md:190-227` says Traefik dynamic file is `traefik-http.json`; `docker-compose.yml:69` uses `traefik-http.yml` (JSON is valid YAML so it works, but docs/config diverge).
- `.env.example:139` Gemini model `gemini-2.0-flash` vs `provider.py:12` `gemini-3.1-flash-lite` vs README `gemini-3.1-flash-lite`; `provider.py:7` adds a third value (F21).
- `.env.example:65-80` describes `noop|traefik_file|kubernetes` with no warning that `kubernetes` is a stub that raises (feature gap #1).
- `.env.example` does not document `VELA_LLM_ALLOW_PRIVATE_ENDPOINTS` (SSRF escape hatch, `core/security/outbound_url.py:11-16`) or `VELA_LLM_CACHE_DIR` (`core/llm/cache.py:16`), both of which materially change security/data locality.
- `README.md:12` describes "PostgreSQL for users and related data" but the log/metric collectors and LLM cache write to Docker stats storage and a local SQLite file respectively; fine but incomplete.

---

## 8. Severity tally

- **Critical: 4** (F1, F2, F3, F4)
- **High: 3** (F5, F6, F7)
- **Medium: 11** (F8–F18)
- **Low/quality: 9** (F19–F27)

Net: the security-hardening branch added useful header/SSRF/secret/credential hardening, but three entire route groups (traffic, images, builder build/analyze) remained unauthenticated, and there is no route-level test asserting authentication, so the most serious issues are structural (missing router dependencies), not subtle logic bugs. Fixing them is a one-line `APIRouter(dependencies=[Depends(get_current_user)])` per module plus a Traefik rule backtick guard — the shortest path that closes four critical holes.
