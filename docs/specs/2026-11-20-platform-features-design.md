# Platform features — design catalog (spec only)

- **Status:** Spec written and approved in chat (2026-11-20). **No feature in this document is implemented in the current work.** Each entry is a candidate for its own future brainstorm → plan → implementation cycle.
- **Purpose:** Capture the useful-but-absent or half-built capabilities surfaced by the full-project review, with enough structure to prioritise later without pretending details are settled.
- **Sources:** `.subagent-reports/review-cli-infra-product.md` (Part C, P1–P11), `.subagent-reports/review-backend.md` (§4 feature gaps), and the delivery specs in `docs/entrega-*.md` for intended product scope.
- **Conventions:** Effort is a rough S/M/L. Layer is backend / frontend / CLI / infra / combinations. Dependencies point at other entries in this catalog. Every entry ends with `Status: Deferred — not implemented.`

---

## Recommended build order (dependency-driven)

1. **F04 Externalized state** — prerequisite for real HA and for reliable backup/restore of job state.
2. **F01 Backups + restore** — once state is externalizable, a restore drill is meaningful.
3. **F02 Metrics export** — the data source for quotas, showback and SLOs.
4. **F03 Compute quotas** — depends on usage data; protects a shared cluster.
5. **F13 Container config update** and **F12 Rollback** — deployment lifecycle basics, both built on deployment records.
6. **F05 Canary / rolling deploys** and **F10 PR previews** — need health gates plus the traffic router.
7. **F14 Secret store**, **F15 Webhooks**, **F06 SBOM/CVE**, **F17 K8s router**, **F18 RPS scaling**.
8. **F07 CLI parity**, **F11 CLI DX**, **F08 Alert digests**, **F09 Showback**, **F16 Volume-upload management** — independent, can be slotted in anytime.

---

## F01 — Scheduled backups + one-click restore

- **Value:** A self-hosted PaaS holds real workloads; today there is no disaster-recovery path for Postgres, Traefik certs, or uploaded folders.
- **Effort / layer:** M · infra + backend.
- **Approach:** Scheduled `pg_dump` + cert/upload archival with local rotation and optional S3/R2 destination; an admin "Restore" action with a dry-run preview; documented restore drill.
- **Dependencies:** F04 (state externalization simplifies consistency).
- **Open questions:** Restore atomicity across DB and object storage; retention policy defaults; whether restore is self-service or admin-only.
- **Status: Deferred — not implemented.**

## F02 — Prometheus / OpenTelemetry export and external alerting

- **Value:** `/api/metrics` is SPA-only JSON and `/api/health` is a bare status string; operators cannot plug Vela into Grafana/Alertmanager/PagerDuty.
- **Effort / layer:** M · backend + infra.
- **Approach:** Add a Prometheus-format `/metrics` scrape endpoint and OTLP export; define a small set of platform SLO signals (API up, collectors healthy, deploy success rate, workload count by state).
- **Dependencies:** none; feeds F03 and F09.
- **Open questions:** Pull vs push in the default compose stack; metric cardinality for per-workload labels.
- **Status: Deferred — not implemented.**

## F03 — Per-team compute quotas and fair limits

- **Value:** Storage quotas and per-container memory limits exist, but nothing caps container count, aggregate CPU/RAM, or deploy rate — one account can starve a shared teaching cluster.
- **Effort / layer:** L · backend + frontend.
- **Approach:** Enforceable per-team compute quotas evaluated at deploy/scale time, with a usage-vs-quota panel and clear 402/409-style errors.
- **Dependencies:** F02 (reliable usage data).
- **Open questions:** Hard vs soft limits; who sets quotas (platform admin vs team owner); behaviour of existing workloads when a quota is lowered.
- **Status: Deferred — not implemented.**

## F04 — HA-ready externalizable state

- **Value:** Deploy jobs, object storage and traffic state are in-process or on local disk, so the API cannot run more than one replica — a hard production ceiling for an orchestration platform.
- **Effort / layer:** L · infra + backend.
- **Approach:** Move deploy job state to Postgres/Redis, avatars/uploads to S3-compatible storage by default in compose, and traffic state to a shared store; make the API stateless so `replicas: >1` works behind Traefik.
- **Dependencies:** none — this is the foundation.
- **Open questions:** Redis vs Postgres for job state; migration path for existing local state; whether the default single-node compose stays simple.
- **Status: Deferred — not implemented.**

## F05 — Progressive delivery: rolling / blue-green / canary

- **Value:** Every deploy swaps the live container immediately with no canary slice, no automatic health gate and no traffic percentage — bad deploys reach all users.
- **Effort / layer:** L · backend + frontend + infra.
- **Approach:** A deploy-strategy selector (recreate / rolling / canary %) with automatic abort on failed healthchecks and traffic shifting through the existing Traefik router.
- **Dependencies:** F04 (shared state for multi-replica routing), traffic router work, healthcheck reliability.
- **Open questions:** Canary metric source (Vela health vs external signals); rollback interaction (F12); how to represent partial traffic in `traefik_file`.
- **Status: Deferred — not implemented.**

## F06 — Vulnerability / SBOM scanning at deploy time

- **Value:** Arbitrary images and Git URLs can be deployed straight to a public route with no scanning — high risk on a teaching platform where students deploy untrusted code.
- **Effort / layer:** M · backend + infra.
- **Approach:** A pipeline stage that generates an SBOM and runs a CVE scan (Trivy/Grype) with a configurable fail threshold and a per-deploy report shown in the UI.
- **Dependencies:** none.
- **Open questions:** Scanner deployment model (sidecar vs service); blocking vs advisory mode; database refresh cadence.
- **Status: Deferred — not implemented.**

## F07 — CLI parity with backend surface

- **Value:** Stacks, projects/teams, Dockerfile templates, scaling policies, metrics, audit and image discovery are first-class backend features with no terminal access, so they cannot be scripted in CI.
- **Effort / layer:** M · CLI.
- **Approach:** Add `vela stack`, `vela projects`/`vela teams`/`vela invite`, `vela templates`, `vela scale`, `vela metrics`, `vela audit`, `vela images`/`vela sources`, `vela settings`/`vela github status`; add `--project` to read commands and a `logs` HTTP-snapshot fallback for stopped containers.
- **Dependencies:** none.
- **Open questions:** Which commands need admin/instructor rights; interactive vs scriptable output modes.
- **Status: Deferred — not implemented.**

## F08 — Alert digests and quiet hours

- **Value:** Alerts are immediate-only; operators are paged for every transient restart. `docs/entrega-3-historias-de-usuario.md:53` explicitly deferred digests.
- **Effort / layer:** S–M · backend + frontend.
- **Approach:** Daily/weekly digest schedules and per-team quiet hours on top of the existing alert + dedup system.
- **Dependencies:** none.
- **Open questions:** Timezone source (team vs user); digest content when there are no incidents.
- **Status: Deferred — not implemented.**

## F09 — Cost / showback dashboard per team

- **Value:** Usage data already exists (`metrics.py` usage endpoints, storage-quota usage); no one can see estimated cost or per-team attribution.
- **Effort / layer:** M · backend + frontend.
- **Approach:** Surface estimated CPU/RAM/storage cost and per-team breakdowns with exportable monthly reports.
- **Dependencies:** F02 (normalized usage data), F03 (quota context).
- **Open questions:** Cost model (raw resource-time vs arbitrary rates); who may see other teams' figures.
- **Status: Deferred — not implemented.**

## F10 — Preview environments per pull request

- **Value:** GitHub OAuth and Git-source deploys already exist; auto-deploying a namespaced, TTL-bound preview per PR with a commented URL is a high developer-UX payoff.
- **Effort / layer:** L · backend + frontend + infra.
- **Approach:** Webhook-driven preview deploys, unique hostname via the traffic router, TTL expiry and garbage collection on PR close.
- **Dependencies:** F15 (webhooks), F05 (routing/health gates), F04 (state for lifecycle tracking).
- **Open questions:** Repo opt-in; resource caps for previews; secret injection for preview builds.
- **Status: Deferred — not implemented.**

## F11 — CLI DX: config, completions, non-blocking run

- **Value:** Repeated friction for daily users — no way to switch server/token non-interactively, no completion scripts, and `vela run` always blocks.
- **Effort / layer:** S · CLI.
- **Approach:** `vela config get|set`, shell completion generation, and a bounded `--no-wait` run that prints the job id.
- **Dependencies:** none (the `--no-wait` half overlaps a defect-wave CLI fix).
- **Open questions:** Where to store multiple server profiles.
- **Status: Deferred — not implemented.**

## F12 — Deploy rollback / redeploy previous version

- **Value:** Deployment history and diff exist but cannot be applied, so recovery from a bad deploy is manual.
- **Effort / layer:** M · backend + frontend.
- **Approach:** A "Redeploy" action on a history entry that reconstructs the recorded source/image/env/command/port and starts a new deploy; keep env secrets redacted via F14.
- **Dependencies:** F13 (config update path), F14 (secret references).
- **Open questions:** Whether a rollback is a new history entry; behaviour when the original image tag no longer exists.
- **Status: Deferred — not implemented.**

## F13 — Update a running container's configuration

- **Value:** Only create/start/stop/restart/remove exist today; changing env, image tag, resources or command requires delete+recreate downtime.
- **Effort / layer:** M · backend + frontend + CLI.
- **Approach:** A PATCH-style endpoint that applies a new deploy config to an existing container as a redeploy, reusing the existing deploy pipeline and history recording.
- **Dependencies:** none.
- **Open questions:** Which fields are in-place vs require recreation; how to surface the diff before applying.
- **Status: Deferred — not implemented.**

## F14 — Secret store / env references

- **Value:** Env vars are supplied inline and redacted to `<REDACTED>` in history, so configs cannot be shared or restored — the security-correct choice left a product hole.
- **Effort / layer:** M · backend + frontend.
- **Approach:** Encrypted per-user/per-team secrets with `secret://name` references in deploy configs, resolved at deploy time; history stores references, not values.
- **Dependencies:** none.
- **Open questions:** Rotation semantics; whether secrets are readable after creation or write-only.
- **Status: Deferred — not implemented.**

## F15 — Git webhooks / push-to-deploy

- **Value:** Deploys are user-initiated only; push-to-deploy is a standard expectation for a platform already wired to GitHub OAuth and Git sources.
- **Effort / layer:** M · backend + infra.
- **Approach:** Per-project webhook endpoint with signature verification, branch filters and a deploy trigger reusing the Git-source pipeline; surface delivery history.
- **Dependencies:** none.
- **Open questions:** Shared-secret vs GitHub App; replay protection; secrets for private repos.
- **Status: Deferred — not implemented.**

## F16 — Volume-upload management endpoint

- **Value:** Users can upload up to 150 MB of volume files but cannot list or delete them, so the quota can only be reclaimed by deleting the container.
- **Effort / layer:** S · backend + frontend.
- **Approach:** `GET`/`DELETE /api/containers/volume-uploads` with ownership checks and an accompanying UI list.
- **Dependencies:** none.
- **Open questions:** Whether deletion is blocked while a container is running.
- **Status: Deferred — not implemented.**

## F17 — Finish the Kubernetes traffic router

- **Value:** `VELA_TRAFFIC_ROUTER=kubernetes` is advertised in the README and `.env.example`, but every method raises "not implemented yet" — a config option that fails at runtime.
- **Effort / layer:** M · backend + infra.
- **Approach:** Implement Ingress/Route resource generation against the Kubernetes API (or remove the option from docs if the platform stays Docker-only).
- **Dependencies:** none.
- **Open questions:** Is Kubernetes a supported deploy target at all, or only an ingress backend? Cluster credentials model.
- **Status: Deferred — not implemented.**

## F18 — Real RPS-based auto-scaling

- **Value:** `REQUESTS_PER_SECOND` currently maps to CPU with a TODO, so the advertised policy does not respond to load.
- **Effort / layer:** M · backend.
- **Approach:** Feed an actual request-rate signal (edge/ingress metrics or app instrumentation) into the scaling engine with target-RPS policies and cooldowns.
- **Dependencies:** F02 (metrics pipeline).
- **Open questions:** Signal source per traffic router; behaviour when no traffic signal is available.
- **Status: Deferred — not implemented.**

## Cross-cutting note: dependency vulnerabilities

`npm ci` in this worktree reports 16 vulnerabilities (7 moderate, 9 high) from the locked dependency tree, including deprecated `xterm`/`xterm-addon-fit`. Triage (safe in-range upgrades vs major migrations) is tracked with the defect-remediation work rather than as a product feature; any change must keep `package.json` on exact versions per `AGENTS.md`.
