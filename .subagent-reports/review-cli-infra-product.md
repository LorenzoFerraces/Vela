# Vela review — CLI, Infra/Deployment/CI, and Product synthesis

Scope: `F:\lolo\fac\Vela`, current checkout (dev + security hardening). Research-only; no source files modified. Findings verified by reading the cited files and cross-referencing backend routes/config. I explicitly avoided the items already listed as covered by the backend and frontend reports.

Legend: **S**everity = Critical / High / Medium / Low for bugs. **E**ffort = S/M/L for product ideas.

---

# Part A — CLI (`cli/`)

## A.0 Architecture summary

Bun-based thin HTTP client over the FastAPI `/api` surface, plus a React/opentui TUI compiled via `bun build --compile`.

- `cli/src/main.ts:12-32` — hardcoded HELP/command table; `main.ts:83-126` is a single `switch` dispatcher; `main.ts:144` `process.exit(await main(...))`.
- `cli/src/client.ts:67-108` — one generic `request<T>()` with Bearer header, 30 s `AbortController` timeout, JSON parse, `toVelaError()` mapping. Clean and the right amount of abstraction.
- `cli/src/config.ts:19-67` — config at `~/.vela/config.json` (or `VELA_CONFIG`), precedence flags > env > file > default, `0o600` write with POSIX chmod fallback. Correct.
- `cli/src/commands/*` — one file per command group; `cli/src/tui/app.tsx` is the only sizeable UI file (300 lines, still scannable).
- Tests: `client.test.ts`, `config.test.ts`, `resolve.test.ts`, `tui/app.test.tsx`. No integration tests, no command-level tests.

Overall the CLI is small, coherent, and does not over-build. Issues below are mostly correctness/parity, not architecture.

## A.1 Bugs / correctness (ranked)

### A1.1 — MEDIUM: `exec` hard-codes a 10-minute session cap, conflicting with the server's 1-hour default
- `cli/src/commands/exec.ts:52-58` sets `setTimeout(..., 600_000)` and closes the socket when it fires.
- The backend allows up to 3600 s: `backend/app/api/routes/containers.py:189-194` (`_exec_max_session_seconds`, default `"3600"`) and `containers.py:1555` uses it as the exec timeout.
- Impact: an interactive `vela exec` session is killed after 10 minutes even though the server would allow an hour. The CLI also silently resolves `0` on normal close (`exec.ts:116-123`) with no "session expired" message, so the user just sees the terminal vanish.
- Fix: read the same env/`VELA_EXEC_MAX_SESSION_SECONDS` value (or simply raise to 3600), and report timeout explicitly.

### A1.2 — MEDIUM: `run`/`waitForJob` can poll forever and has no escape hatch
- `cli/src/commands/deploy.ts:34-56` loops `for (;;)` with `Bun.sleep(1000)` until the job is `succeeded`/`failed`. There is no max wall-clock, no `--no-wait`/`--wait=false`, and no backoff.
- The per-request 30 s timeout (`client.ts:77-78`) does not bound the loop. A job stuck `in_progress` hangs the CLI indefinitely.
- Related: the job registry is in-memory (`backend/app/core/deploy/jobs.py`, also noted in the backend report). If the API restarts mid-deploy, `deploys/active` no longer returns the id and the CLI throws `"Deploy job disappeared before completing."` (`deploy.ts:42-44`) even though the container may have been created. Terminal jobs *are* kept visible (`backend/tests/test_deploy_jobs.py:203`), so the common fast-deploy race is not a problem — only API restarts.
- Fix: add a `--no-wait` flag (print id and exit) plus a bounded poll with a clear timeout error.

### A1.3 — MEDIUM: container-name resolution only sees one unpaginated page
- `cli/src/resolve.ts:31-43` resolves a query by fetching `GET /containers/` and filtering client-side.
- The backend deliberately caps the default page: `backend/app/api/routes/containers.py:617` — `ponytail: default limit = max page so the un-paginated UI still gets every container`. So with more containers than that cap, `vela logs <name>`, `vela exec <name>`, `describe`, and all lifecycle commands will report `Container "<query>" not found.` for a real container.
- Fix: pass the backend's explicit `limit`/pagination params (or an exact-name lookup endpoint) rather than assuming "all".

### A1.4 — LOW/MEDIUM: `login --server` is dead code
- `cli/src/main.ts:42-70` `applyGlobalConfig()` strips `--server`/`--token` from argv *before* dispatch and publishes them as env vars.
- `cli/src/commands/auth.ts:32-38` still declares and reads `values.server` from `parseArgs`, which can therefore never be populated by `vela login --server ...`. It happens to work only because `login.ts:38` falls back to `process.env.VELA_API_URL` that `applyGlobalConfig` just set.
- Harmless today, but it is two sources of truth for the same flag; remove the `parseArgs` `server` option or stop pre-stripping.

### A1.5 — LOW: `run` (and TUI) hard-code git branch `main`
- `cli/src/commands/deploy.ts:98` and `cli/src/tui/index.tsx:33` use `git_branch: "main"` as the only default. Repos whose default branch is `master`/`develop` fail to build unless the user knows to pass `--branch`. Prefer letting the backend/analyzer infer the default branch when `--branch` is omitted.

### A1.6 — LOW: mixed output streams and shell-quoting in `exec`
- `cli/src/commands/exec.ts:108-114` writes text frames to **stderr** with an appended newline and binary frames to stdout. Pipelining `vela exec ... -- cat file` therefore splits output across streams.
- `exec.ts:101-104` quotes an argument only if it contains whitespace; shell metacharacters are passed through and the whole line is suffixed with `; exit`. It is typed into a real shell by design, so this is not a new injection boundary, but arguments containing `;`/newlines behave surprisingly.

### A1.7 — LOW: `formatTable` does not bound column width
- `cli/src/format.ts:1-11` pads to the longest cell. A long `access_url` or `source_ref` makes `ps`/`deploys` unreadable on an 80-column terminal. Truncate with ellipsis at a sane max width.

## A.2 Auth / token handling

- `cli/src/commands/auth.ts:47-58` — login exchanges email/password for a short-lived `access_token`, immediately mints a long-lived PAT named `cli:<hostname>`, and stores only the PAT. Password is never persisted. Good.
- `cli/src/commands/auth.ts:65-81` — logout revokes the stored PAT via `DELETE /tokens/{tokenId}` and best-effort ignores failures, then removes the local file. If the token came from `VELA_TOKEN` there is no `tokenId`, and the message correctly tells the user to revoke it at the issuer.
- `cli/src/config.ts:38-49` — config written with `mode: 0o600` and an explicit chmod; Windows correctly documented as ACL-governed. Good.
- **Note (not a CLI bug):** the PAT minted at `auth.ts:53-58` has no expiry argument — this is the already-flagged backend "PAT expiry" item, mentioned here only so the CLI token lifecycle is not mistaken for a separate issue.
- **Security UX gap (LOW):** `--token <pat>` (`main.ts:63-65`) puts a secret in shell history and the process argument list. README `cli/README.md:24-29` does recommend env vars for CI, but the global flag remains documented (`main.ts:31`). Prefer `VELA_TOKEN`/stdin or print a warning when `--token` is used.

## A.3 TUI

- `cli/src/tui/index.tsx:9-73` builds the renderer, loads containers, and wires callbacks. `app.tsx:71-88` polls every 5 s.
- **Half-built (MEDIUM):** `app.tsx:146-148` — pressing `l` ("logs") does **not** show logs; it appends the literal string `-- following <name> is handled by: vela logs <name> -f` into a local array. Likewise `index.tsx:62-66` `onExec` merely destroys the renderer and prints `Run: vela exec <name>`. The key legend advertises `l` and `e` (`app.tsx:294-295`) as working features. Either implement an embedded log pane or remove the keys/labels.
- `index.tsx:26-36` TUI deploy always sends `git_branch: "main"`, no name/port/env/public, and does not wait for the job. Deliberately minimal, but inconsistent with `vela run`.
- `app.tsx:108-153` handles `q` even while a modal is open? No — the `deploying` branch returns early, so Escape cancels; acceptable.

## A.4 Tests

- Existing: `client.test.ts` (error mapping/exit codes), `config.test.ts` (precedence, 0600 mode, corrupt-file fallback), `resolve.test.ts` (exact/prefix/ambiguous), `tui/app.test.tsx` (3 render/interaction tests).
- Gaps: **no tests for any command** — `waitForJob` polling/timeout, `parseEnv`, `isGitSource`, the `exec` 600 s timer, WS URL construction, `applyGlobalConfig` stripping, and the `logs`/`tokens`/lifecycle flows are all untested. A small `deploy.test.ts` covering `parseEnv` + `waitForJob` with an injected fetch would catch the two most likely regressions (A1.1/A1.2). CI only runs `bun test` + `tsc --noEmit` + compile smoke (`.github/workflows/ci.yml:42-64`).

## A.5 Missing CLI commands vs available backend endpoints

The CLI covers auth, containers, run, logs, exec, lifecycle, deployments, and tokens. The backend exposes substantially more. Useful, high-value omissions:

| Backend surface (evidence) | Missing CLI command | Value |
|---|---|---|
| `backend/app/api/routes/stacks.py:86,95,190,202,233,344` (list/create/get/update/delete/deploy + parse-manifest/analyze-repo) | `vela stack <list\|deploy\|up\|rm\|manifest>` | Compose-stack deploys are a first-class product feature with no terminal access at all. |
| `projects.py:77-401` (projects, invitations, members, roles, storage quota) / entrega-3 Teams | `vela projects`, `vela teams`, `vela invite` | Team workflows are CLI-invisible; cannot script onboarding or switch active project. |
| `dockerfile_templates.py` (Builder templates) | `vela templates <list\|create\|rm>` | Cannot reuse saved Dockerfiles outside the UI. |
| `scaling.py:43,59,82` (list/get/put policies) | `vela scale` / `vela scaling` | Scaling policies cannot be inspected or edited from a terminal. |
| `metrics.py:1,42` (usage/metrics history) | `vela metrics <name>` | `describe` shows a single stats snapshot; no history/trend in CLI. |
| `audit.py` | `vela audit` | Cannot export/inspect the audit trail in scripts. |
| `images.py`, `containers/deploy-sources` | `vela images`, `vela sources -q` | No deploy-source discovery to feed `vela run`. |
| `settings.py`, `github.py` | `vela settings`, `vela github status` | Cannot check OAuth connection state from CI. |
| — | `vela config <get\|set>` | Only `login` writes config; no supported way to switch server/token non-interactively except env vars. |
| — | shell completions (`vela completion bash\|zsh\|powershell`) | Pure DX; standard for a dev-focused CLI. |

Also missing flags on existing commands: `run --cmd` (backend supports `command`, entrega-2 story 3), `run --wait/--no-wait`, `--project` on all read commands, and a `logs` HTTP-snapshot fallback for stopped containers (`backend/app/api/routes/logs.py` has a snapshot endpoint; CLI `logs.ts:30` only opens the WS stream).

---

# Part B — Infra / deployment / CI

## B.1 Bugs and blockers (ranked)

### B1.1 — HIGH: folder uploads fail on a fresh Linux host (default bind dir is root-owned)
- `docker-compose.yml:77-85`: `VELA_VOLUME_UPLOADS_DIR=/data/volume-uploads`, `VELA_VOLUME_UPLOADS_HOST_DIR` defaults to empty, so the bind at line 85 becomes `/data/volume-uploads:/data/volume-uploads`.
- `docker-compose.yml:62` starts as root but `backend/entrypoint.sh:36-38` unconditionally `setpriv --reuid=vela`, i.e. uid 1000.
- `backend/app/core/containers/volume_uploads.py:43-47` resolves the root to the configured `/data/volume-uploads`, and `save_volume_upload()` creates it with `exist_ok=False`. The `chown -R vela:vela /data` in `backend/Dockerfile:30-31` is applied to the image layer and is hidden by the bind mount.
- On a fresh Linux host the daemon creates the missing bind source as `root:root 0755` → uid 1000 gets `EACCES` → folder-upload 500s. `.env.example:219-226` documents the workaround but the default remains broken. (This corroborates B1 in the existing `linux-deploy-audit.md:11-18`.)
- Fix: ship a named volume for uploads (and pass the host mirror explicitly via `VELA_VOLUME_UPLOADS_HOST_DIR`), or pre-create the dir in the image/compose init.

### B1.2 — HIGH: CI never validates infra, and infra edits do not even trigger CI
- `.github/workflows/ci.yml:3-15` — `paths` filters include only `backend/**`, `frontend/**`, `cli/**`, and the workflow. `docker-compose.yml`, `docker-compose.dev.yml`, `.env.example`, `backend/Dockerfile`, `backend/entrypoint.sh`, `frontend/Dockerfile`, `frontend/nginx.conf`, `traefik/**`, and `resources/**` are all excluded.
- No job runs `docker compose config -q`, `docker compose build`, or a `docker compose up -d` smoke, even though `AGENTS.md:Verification` requires exactly that locally before calling a change complete.
- Impact: the hardware/host-specific traps below (B1.1, B2.x) and any compose/YAML drift can merge and break real deployments with a fully green CI.

### B1.3 — MEDIUM/HIGH: documented quickstart produces a non-booting API
- `docker-compose.yml:3-4` and `.env.example:3-5` say `cp .env.example .env && docker compose up -d --build`.
- `.env.example:10-20` marks `VELA_AUTH_SECRET` and `VELA_TOKEN_ENCRYPTION_KEY` **Required** but leaves both empty.
- The app fails closed: `backend/app/core/auth/tokens.py:28-31` raises when `VELA_AUTH_SECRET` is unset, and `backend/app/core/oauth/state.py:37-40` likewise. `migrate` would succeed (it does not need the secret), then `api` crashes.
- Fix: either generate secrets in the quickstart (the file already shows the `python -c ...` commands) or fail early with a clear `docker compose config` check. Do **not** add insecure default values.

### B1.4 — MEDIUM: Node version drift between CI and the production frontend image
- CI uses Node **22** (`.github/workflows/ci.yml:82-85`); `frontend/Dockerfile:1` builds on `node:20-alpine`.
- A dependency or build flag that behaves differently on 20 vs 22 passes CI and breaks `docker compose up -d --build web`. Pin CI to 20 to match the image (or upgrade the image and CI together).

## B.2 Config drift and insecure defaults

- **Hardcoded deployment domain** — `docker-compose.yml:117` defaults `VELA_DOMAIN` to `velaunq.ddns.net`; `.env.example:87` repeats it; `traefik/static/spa.yaml:28-29` reads it via `{{ env "VELA_DOMAIN" }}`; `frontend/vite.config.ts:8` has the same literal as the `allowedHosts` fallback. Meanwhile `.env.example:93` sets `VELA_FRONTEND_BASE_URL=http://localhost` and `:101` sets the OAuth callback to `http://localhost/...`. A fresh deploy therefore advertises a DDNS cert domain but generates localhost OAuth URLs — TLS and GitHub callback drift out of the box. Neutral defaults (empty domain, localhost) or one shared source would be better.
- **Weak default DB password** — `docker-compose.yml:22` and `.env.example:29` default `POSTGRES_PASSWORD=vela`. Acceptable for local dev, but there is no first-run guard or warning for a public host.
- **Traefik dashboard enabled** — `docker-compose.yml:130-135` sets `--api.insecure=true` and publishes `127.0.0.1:8080:8080`. Loopback binding mitigates remote exposure, but the insecure dashboard is on by default in a "production" compose file; gate it behind an env flag.
- **No HTTP→HTTPS redirect** — `traefik/static/spa.yaml:11-15` serves a plain-HTTP `PathPrefix(`/`)` router with no redirect to the `websecure` router, so typing the bare domain keeps all traffic (including the SPA and `/api`) on HTTP. HSTS is applied only on the TLS entrypoint (`docker-compose.yml:123-125`), so HTTP visitors never receive it.
- **Undocumented knob in local `.env`** — `.env:209` sets `VELA_API_CONTAINER_USER=root`, referenced by `docker-compose.yml:57-62` but absent from `.env.example`. Anyone copying the example gets a different container-user path than the checked-in dev setup.
- **nginx body cap vs configurable app cap** — `frontend/nginx.conf:21` hard-codes `client_max_body_size 105m` against the 100 MiB default (`docker-compose.yml:77`, `.env.example:228-229`). Raising `VELA_VOLUME_UPLOAD_MAX_BYTES` above 105 MiB makes nginx return 413 before the app's clearer error — a silent config ceiling.
- **ACME email optional / no staging resolver** — `docker-compose.yml:126` defaults `VELA_TRAEFIK_ACME_EMAIL` to empty and uses only the production Let's Encrypt HTTP challenge. A typo in `VELA_DOMAIN` or a firewalled port 80 burns production rate limits with no staging fallback.
- **Local `.env` holds live-looking credentials** — the working-tree `.env` contains Clerk/GitHub/R2/Brevo/admin values. It is correctly gitignored (`.gitignore:13`; `git ls-files --error-unmatch .env` confirms it is **not** tracked), so this is a local hygiene note, not a committed-secret finding.

## B.3 Production readiness / single points of failure

- Single Postgres (`docker-compose.yml:16-30`), single API (`:50-97`), single Traefik (`:112-145`), single web (`:99-110`). `restart: unless-stopped` handles process death only.
- Horizontal scaling is blocked by design-level in-memory state: deploy jobs (backend report), object storage `VELA_OBJECT_STORAGE=memory` (`.env.example:117-119`, avatars lost on restart), and the traffic-state files under `resources/`. Making these externalizable is the prerequisite for HA (see product idea P4).
- **No container resource limits or hardening** on any compose service: no `mem_limit`/`cpus`/`pids_limit`, no `security_opt: no-new-privileges`, no `read_only`. A runaway api/postgres/Traefik can starve the host. This is separate from the per-workload `DeployConfig.memory_limit` the app already supports (`backend/app/core/models.py:129`).
- **No backup/restore path** for `postgres_data`, `traefik_certs`, or the uploads bind (see P1).
- **Upgrade/rotation hazards** documented but unmanaged: changing `POSTGRES_*` requires deleting the volume (`.env.example:26-27`); changing `VELA_TOKEN_ENCRYPTION_KEY` makes stored OAuth tokens unreadable (`.env.example:17-20`). There is no re-key/rotation migration.

## B.4 CI gaps (what is not tested)

- No backend lint (`ruff check .`) or typecheck (`mypy app/ tests/`) — both are documented in `AGENTS.md:Commands` but absent from `ci.yml:18-40`.
- No frontend lint/typecheck/production build — `ci.yml:66-108` runs only Playwright (which uses the Vite dev server), so a `tsc -b && vite build` regression or an ESLint error merges silently.
- No CLI test on Windows, despite `dist/vela.exe` being a shipped artifact — the Windows-only chmod/ACL and TTY paths (`config.ts:44-48`, `prompt.ts:21-29`, `exec.ts:31-36`) are exercised only on Ubuntu.
- `bun-version: latest` (`ci.yml:47-49`) makes CLI builds non-reproducible; the CLI relies on a Bun-specific WebSocket header extension (`cli/src/ws.ts:33`, `cli/src/commands/exec.ts:50`), so a runtime change could break `logs`/`exec` with no code change. Pin it.
- No compose validation job at all (B1.2).

---

# Part C — Product-level "missing / half-built" synthesis

Read scope: `docs/entrega-poc-historias-de-usuario.md`, `docs/entrega-1-historias-de-usuario.md`, `docs/entrega-2-historias-de-usuario.md`, `docs/entrega-3-historias-de-usuario.md`. Delivered scope: monorepo + Docker orchestration + Traefik public routes; auth/teams + GitHub OAuth + logs/monitoring + image suggestions; Builder templates + unified source combobox + env/command + Git AI prefill + deployment history/diff; email alerts + Teams/RBAC (Viewer/Operator/Owner) + shared deploy history. Items below are not in the backend/frontend exclusion lists.

### P1 — Scheduled backups + one-click restore — **HIGH value · M · infra+backend**
Back up `postgres_data`, `traefik_certs`, and the uploads bind on a schedule (local rotation + optional S3/R2), with a documented restore drill and a "Restore" admin action. The spec never mentions disaster recovery and nothing in compose does it. For a self-hosted PaaS holding real workloads this is the single highest-value missing capability.

### P2 — Prometheus / OpenTelemetry export and external alerting — **HIGH value · M · backend+infra**
`GET /api/metrics` (`backend/app/api/routes/metrics.py:1,42`) is a JSON time-series API for the SPA, and `/api/health` is a bare `{"status":"ok"}` (`app.py:309-311`). There is no scrape endpoint, trace, or platform-level SLO signal. Expose `/metrics` in Prometheus format + OTLP export so operators can plug Vela into Grafana/Alertmanager/PagerDuty instead of relying only on Brevo email (`entrega-3` story 1).

### P3 — Compute quotas and per-team fair limits — **HIGH value · L · backend+frontend**
Storage quotas exist (`VELA_TEAM_STORAGE_QUOTA_BYTES`, `.env.example:233-235`; `backend/app/core/quotas/`), and per-container memory limits exist (`core/models.py:129`), but there is no cap on **number of containers**, aggregate CPU/RAM, or deploy rate per team. On a shared teaching cluster one account can starve everyone. Add enforceable per-team compute quotas with a usage/quota UI and a clear 402/409-style error.

### P4 — HA-ready externalizable state — **HIGH value · L · infra+backend**
Move deploy jobs, traffic state, and object storage out of process (Redis/Postgres + S3-compatible) so `api` can run >1 replica behind Traefik. Today single-replica is mandatory (see B.3), which is a production-readiness ceiling for a platform whose whole pitch is orchestration.

### P5 — Progressive delivery: health-gated rolling / blue-green / canary — **HIGH value · L · backend+frontend+infra**
Backend report already flags "no rollback"; the *forward* problem is also unbuilt: every deploy swaps the live container immediately with no canary slice, no automatic health gate, and no traffic percentage. Add a deploy strategy selector (recreate / rolling / canary %) with automatic abort on failed healthchecks. Distinct from an undo button — this prevents bad deploys from reaching all users.

### P6 — Vulnerability/SBOM scanning at deploy time — **HIGH value · M · backend+infra**
`POST /api/containers/run` accepts arbitrary images/Git URLs (POC story 3; `deploy.ts:84-102` mirrors it in CLI) with no image scanning before exposure via a public Traefik route. Generate an SBOM and run a CVE scan (Trivy/Grype) as a pipeline stage with a configurable fail threshold and a per-deploy report. High value for a teaching platform where students deploy untrusted images.

### P7 — CLI parity for stacks / projects / templates / scaling — **MEDIUM-HIGH value · M · CLI**
Full command matrix in A.5. Prioritize `vela stack` and `vela projects/teams` — multi-container stacks (entrega-2 era) and Teams (entrega-3) are flagship features entirely absent from the terminal client. Adds scriptability and CI use cases the SPA cannot serve.

### P8 — Daily/weekly alert digests and quiet hours — **MEDIUM value · S-M · backend+frontend**
`entrega-3.md:53` explicitly defers "resúmenes diarios o semanales." Current alerts are immediate-only with dedup (`entrega-3` story 1). Add a digest schedule + quiet hours per team so operators are not paged for every transient restart — a natural, cheap follow-up to the delivered anti-duplication.

### P9 — Cost/showback dashboard per team — **MEDIUM value · M · both**
The data already exists: `metrics.py` `ProjectUsage`/`UsageSummary` and storage-quota usage endpoints (`projects.py:206`). Surface estimated CPU/RAM/storage cost and per-team breakdowns with exportable monthly reports. Strong fit for a shared/teaching cluster where fairness and attribution matter.

### P10 — Preview environments per pull request — **MEDIUM value · L · both+infra**
Leverage existing GitHub OAuth (`entrega-1` story 2) and Git-source deploys (`entrega-2` story 4) to auto-deploy a namespaced, TTL-bound preview per PR with a comment posting the public URL, and garbage-collect on close/expiry. High developer UX payoff; natural extension of the already-built analyzer + Traefik router.

### P11 — `vela config` + shell completions + bounded `--no-wait` run — **LOW-MEDIUM value · S · CLI**
Pure DX: persistent server/token switching, completion scripts, and a non-blocking `run` (fixes A1.2). Small diff, removes repeated friction for daily users.

---

## Counts

- **Bugs/defects:** 4 High/Critical–Medium (B1.1, B1.2, B1.3, B1.4) infra + 7 CLI (3 Medium, 4 Low) + TUI half-build = **13 concrete defects/gaps** (7 Medium-or-higher, 6 Low).
- **Config/drift/security/prod-readiness notes:** 11 (B2/B3) + 5 CI gaps (B4).
- **Product ideas:** 11 ranked (4 HIGH, 3 MEDIUM-HIGH/MEDIUM, 1 LOW-MEDIUM), with effort and layer per item.
