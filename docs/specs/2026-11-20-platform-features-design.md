# Platform features — active design spec (12 features)

- **Status:** Design approved in chat 2026-11-22. No feature below is implemented by this spec; each group gets its own implementation plan (A–D).
- **Supersedes:** the 18-entry catalog dated 2026-11-20. The six features not selected for this cycle live in `docs/specs/2026-11-22-deferred-platform-features.md`.
- **Context:** the catalog was committed as `17c90bb`; current HEAD is `f379842` (32 later commits). Open questions were researched in `.subagent-reports/catalog-open-questions-research.md` (untracked). Stale catalog premises to keep in mind: F11's `--no-wait` is already shipped (`e436487`); deploy history now stores a full Fernet-encrypted `DeployConfig` snapshot with a loader (`3f8e3b4`), so F13/F14 have a real source of truth; F05's backtick-injection concern was already fixed (`c0b99c1`); F16 upload hardening landed; F17 docs are half-corrected (`.env.example` says "scaffold", README still advertises it as normal).
- **Conventions:** Effort S/M/L. Dependencies point at other features in this spec. Every group ends with its own plan.

---

## Locked decisions

| Feature | Decision |
|---|---|
| F02 | Pull-style Prometheus `/metrics` on the API, no new compose service; bounded labels only; scrape protected by a static `VELA_METRICS_TOKEN` bearer (not a public endpoint); includes the edge request counter F18 needs. `vela_deploy_success_rate` = succeeded/(succeeded+failed) over terminal `deploy_jobs` rows in the last 24h (0.0 when none). |
| F03 | Hard-fail compute quotas at deploy/scale, mirroring storage quotas; team OWNER sets limits within an admin-owned ceiling; lowering a quota never stops or deletes running workloads. |
| F04 | Full externalization of job state, object storage and traffic state; single-node compose stays the default; multi-replica is opt-in. |
| F07 | CLI parity commands plus uniform `--json`/`--quiet` scriptable output; respect existing admin/instructor gates. |
| F09 | Raw resource-time showback only (CPU-seconds, memory GiB-hours, storage GiB-days); no invented currency; team members see their own team, admins see all. |
| F10 | Explicit repo opt-in; existing health endpoint + monitor for readiness (no F05/canary); low fixed caps and short TTL; no production secrets or `secret://` references in previews. |
| F11 | Named profiles in the existing config file (`{profiles, active}`), `VELA_PROFILE` override, legacy flat-shape migration; completions. `--no-wait` already done. |
| F13 | `PATCH` that redeploys through the existing pipeline/history; mutable fields in place, identity/topology fields require recreation; dry-run returns the existing diff shape extended with non-secret fields. |
| F14 | Write-only named secrets encrypted with the existing Fernet helper; immutable versions; `secret://name@version` or `latest` resolved at deploy time; history stores references only. |
| F15 | **GitHub App installation** model (chosen over a per-project HMAC secret): App credentials plus per-installation tokens, signature verification over the raw body plus per-delivery-id dedup (unique constraint), with a server-side freshness check on `received_at`, branch filters, delivery history. |
| F17 | Remove `kubernetes` from README and `.env.example`, reject the value at config load with a clear error, and delete the dead adapter. No Kubernetes implementation. |
| F18 | Target-RPS scaling from F02's edge request counter with cooldowns; fail closed to "no scale action" plus "signal unavailable" status; `noop` router keeps its documented CPU proxy. |

## Dependency order

```
B (F04) ────────────────────────────┐
A (F02) ──┬── F03                   │
          ├── F09                   ├──> F10 (in C)
          └── F18                   │
C: F14 ──┬──> F13                   │
         └──> F10 <─────────────────┘
   F15 ──────> F10
D: F11, F07 — independent of the backend groups
F17 — documentation/config only
```

Implementation order: **D** (isolated, may overlap one backend group), **B** (foundation), **A**, **C**, with F10 last in C because it waits on F04, F14 and F15. Plans may be written separately and in parallel; implementation stays sequential per `AGENTS.md`.

---

## Group A — Observability & limits (backend + frontend)

### F02 — Prometheus export and edge request counter

- Add a Prometheus-format `GET /metrics` scrape endpoint on the API. Pull model; no collector service in the default compose stack.
- Protect the endpoint with a static bearer token from `VELA_METRICS_TOKEN`; it is not a public route. The token is required only when the endpoint is enabled.
- Export bounded series only: platform signals (`api_up`, collector health, deploy success rate, workloads by state) and per-project aggregates (project id/name). No per-container labels by default — detailed per-container data stays behind the existing authenticated JSON endpoints.
- Add an edge request counter sourced from Traefik access logs, counted per router/hostname in a rolling window, and expose the derived request rate through `/metrics` as a bounded per-project signal for F18. Reuse the existing access-log location from the compose stack; if the default router emits no usable log, make the counter opt-in and F18 reports "signal unavailable".
- Reuse the existing metrics collector and access-scoping helpers rather than introducing a new metrics library.

### F03 — Per-team compute quotas and fair limits

- Enforceable per-team limits at deploy/scale time: running container count, aggregate CPU limit (millicores), aggregate memory limit (bytes), and deploys per rolling hour.
- Admission is hard: reject with a clear 409-style error naming the exhausted quota; never kill running workloads.
- Two-tier ownership: platform admin owns the ceiling (env config); team OWNER sets the team's limits within that ceiling; members may read only.
- Lowering a quota leaves existing workloads running and blocks further growth; show a warning banner when usage is at or over quota.
- Add a usage-vs-quota panel to the frontend and reuse the existing alert path for over-quota state.
- Evaluate quotas at the same admission points as `enforce_team_storage_capacity()` so deploys, scales and uploads share one gate.

### F09 — Cost / showback dashboard per team

- Report raw resource-time only: CPU-seconds, memory GiB-hours, storage GiB-days, grouped by team. No currency, no hardcoded rates.
- Data comes from the existing `ContainerMetric` rows and storage-quota usage; reuse the same project/team access scoping as `/api/metrics/usage`.
- Team members see their own team's figures; platform admins may see all teams; no cross-team self-service browsing.
- Frontend dashboard with a per-team breakdown and an exportable monthly report (CSV).

### F18 — Real RPS-based auto-scaling

- `ScalingMetric.REQUESTS_PER_SECOND` reads the edge request rate exposed by F02 instead of mapping to CPU.
- Target-RPS policies with the existing cooldown/stabilization gates.
- Fail closed: if the chosen signal is unavailable, do no scale action and surface "signal unavailable" in policy status/UI — never silently substitute CPU.
- The `noop` traffic router keeps its current CPU-proxy behaviour, explicitly documented as a proxy.

---

## Group B — State & routing (infra + backend)

### F04 — HA-ready externalizable state

- Deploy job state: replace the in-process `dict` with a Postgres table; keep the existing 300 s TTL sweep. No job migration is needed — jobs already die on restart.
- Object storage: make the compose default use the S3/R2-compatible backend (`boto3` is already a dependency). Keep the in-memory backend for dev/tests and local runs.
- Traffic state: move off the local `.vela-traffic-state.json` into a shared store (Postgres), with a one-shot importer for existing local state files.
- Make the API stateless so `replicas: > 1` works behind Traefik; expose multi-replica as an opt-in profile, not the default.
- Keep the default single-node compose profile unchanged in shape (one API, one Postgres, one Traefik, one web).

### F17 — Drop the Kubernetes router option

- Remove `kubernetes` from README and `.env.example` (including the "(scaffold)" mention).
- Reject `VELA_TRAFFIC_ROUTER=kubernetes` at config load with a clear "unsupported router" error listing supported values.
- Delete the dead `kubernetes_traffic_router` adapter and remove its wiring from the router factory. No Ingress/Route implementation.

---

## Group C — Deploy lifecycle & secrets (backend + frontend + infra)

Order within group: F14 first, then F13 and F15; F10 last.

### F14 — Secret store / env references

- Named secrets encrypted with the existing Fernet helper; scoped per user or team following existing ownership rules.
- Write-only: create/update returns name and metadata only; reads never return plaintext (matching deploy-history redaction and the LLM-key `has_key` precedent).
- Immutable versions: rotation creates a new version. Deploy configs reference `secret://name@version`, or `secret://name@latest` resolved at deploy time. Running workloads keep the version they were deployed with until redeployed.
- Resolve references at deploy time; deploy history stores references, never values, so configs are shareable and restorable without leaking secrets.
- Secrets introduced here are available to F13's config update and usable by F15/F10 only under F10's preview restriction.

### F13 — Update a running container's configuration

- Add a `PATCH`-style endpoint that applies a new deploy config through the existing deploy pipeline and writes a normal history entry.
- Runtime-mutable fields (env, command, labels, `health_check`, route fields, cpu/memory limits where the engine allows update) redeploy in place.
- Identity/topology fields (name, image, ports, volumes, network, network aliases) require recreation; return a clear error rather than silently recreating.
- Add a dry-run endpoint returning the existing `DeploymentDiffResponse` shape, extended with the non-secret `DeployConfig` fields. Secret values stay `<REDACTED>` and are never echoed back.
- Reuse the encrypted `DeployConfig` snapshot loader as the source of truth, and reuse the existing review/diff UI panel.

### F15 — Git webhooks / push-to-deploy via GitHub App

- Use a GitHub App installation as the integration model: store the App id, encrypted private key and webhook secret; track installation ids per project; derive short-lived installation access tokens for deploys.
- Per-project webhook endpoint with signature verification using the App webhook secret.
- Replay protection: signature verification over the raw body plus per-delivery-id dedup (unique constraint), with a server-side freshness check on `received_at`, mirroring the existing alert-dedup pattern.
- Branch filters per project; trigger a deploy that reuses the Git-source pipeline, using the installation token for private-repo clones (no PAT in the deploy form).
- Surface webhook delivery history in the UI.
- Admin/instructor gating: only project OWNER (or platform admin) may configure webhooks and view/manage App credentials.

### F10 — Preview environments per pull request

- Explicit per-repository opt-in as a project setting; never auto-enable on every connected repo.
- Webhook-driven (F15) deploy of a namespaced preview with a unique hostname from the existing traffic router.
- Resource caps: a low fixed CPU/memory ceiling and a short TTL, enforced at admission and reusing the team quota gate so previews do not silently consume production quota.
- Readiness and status from the existing container health endpoint and background monitor; abort/mark failed on stopped/unhealthy previews. No canary or traffic-percentage work — F05 remains deferred.
- Never inject production secrets into previews. `secret://` references and production env values are denied for preview deploys, especially fork PRs; previews get a dedicated, clearly named env set.
- Garbage-collect previews on PR close (or TTL expiry) and on project/repo opt-out.

---

## Group D — CLI (isolated in `cli/`)

### F11 — CLI DX: config, completions, non-blocking run

- Change config to named profiles in the existing file: `{ "profiles": {...}, "active": "..." }` at `~/.vela/config.json` (or `VELA_CONFIG`), still written `0600`.
- Add `VELA_PROFILE` override for the active profile, and migrate the legacy flat `{server, token, tokenId}` shape on first load.
- Add `vela config get|set|use` and shell completion generation (bash/zsh/fish/PowerShell).
- `run --no-wait` already exists; keep it. No change to bounded polling.

### F07 — CLI parity with backend surface

- Add commands for existing backend features: `vela stack`, `vela projects` / `vela teams` / `vela invite`, `vela templates`, `vela scale`, `vela metrics`, `vela audit`, `vela images` / `vela sources`, `vela settings` / `vela github status`.
- Add `--project` to read commands and a `logs` HTTP-snapshot fallback for stopped containers.
- Add a uniform `--json` / `--quiet` scriptable output mode with stable machine-readable fields; keep the TUI opt-in and bound human table columns.
- Mirror backend rights: image/build/route/admin commands are admin-only; project member/invitation mutations are instructor-or-owner; ordinary deploy/stack/metrics/audit commands stay at normal user scope.

---

## Cross-cutting

- **Specs location:** `docs/specs/` in the worktree at `C:\Users\lolo\.local\share\opencode\worktree\ab1b01\defect-remediation`, committed on the current branch.
- **Verification:** per `AGENTS.md` — backend pytest, frontend Playwright E2E, lint/typecheck, and `docker compose config` + up/smoke/down after substantive changes. CLI changes get their own tests.
- **No new dependencies by default** except where a locked decision requires one (GitHub App support in F15). Keep existing exact-version pinning in `frontend/package.json`.
- **Out of scope here:** F01, F05, F06, F08, F12, F16 (see `2026-11-22-deferred-platform-features.md`). The npm vulnerability triage noted in the old catalog is tracked with defect remediation, not as a product feature.
