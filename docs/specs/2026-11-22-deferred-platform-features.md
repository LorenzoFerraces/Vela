# Platform features — deferred catalog (6 features)

- **Status:** Deferred — not implemented. Moved here from `2026-11-20-platform-features-design.md` on 2026-11-22; that spec now covers only the 12 features selected for this cycle.
- **Conventions:** Effort is a rough S/M/L. Layer is backend / frontend / CLI / infra / combinations. Open questions and code evidence were researched in `.subagent-reports/catalog-open-questions-research.md` (untracked); consult it before picking any of these up.
- **Note:** F10 (PR previews) was selected for this cycle but no longer depends on F05 — its readiness gate uses the existing container health endpoint and monitor instead of canary traffic-splitting.

---

## F01 — Scheduled backups + one-click restore

- **Value:** A self-hosted PaaS holds real workloads; there is no disaster-recovery path for Postgres, Traefik certs, or uploaded folders.
- **Effort / layer:** M · infra + backend.
- **Approach:** Scheduled `pg_dump` + cert/upload archival with local rotation and optional S3/R2 destination; an admin-only "Restore" action with a dry-run preview; documented restore drill. Do not promise atomicity across DB and object storage — publish an RPO instead; suggested retention 7 daily + 4 weekly, 30-day cap, all env-configurable.
- **Dependencies:** F04 (state externalization simplifies consistency).
- **Status: Deferred — not implemented.**

## F05 — Progressive delivery: rolling / blue-green / canary

- **Value:** Every deploy swaps the live container immediately with no canary slice, health gate or traffic percentage — bad deploys reach all users.
- **Effort / layer:** L · backend + frontend + infra.
- **Approach:** Deploy-strategy selector (recreate / rolling / canary %) with automatic abort on failed healthchecks and traffic shifting through the Traefik router. Requires weighted `BackendServer`/`RouteSpec` support — today's route emits equal-weight servers only. Use Vela's existing health data as the mandatory abort gate; external signals later.
- **Dependencies:** F04 (shared state for multi-replica routing), traffic router work, healthcheck reliability.
- **Status: Deferred — not implemented.**

## F06 — Vulnerability / SBOM scanning at deploy time

- **Value:** Arbitrary images and Git URLs can be deployed straight to a public route with no scanning — high risk on a teaching platform where students deploy untrusted code.
- **Effort / layer:** M · backend + infra.
- **Approach:** A pipeline stage that generates an SBOM and runs a CVE scan (Trivy/Grype) via a single shared scanner service; advisory by default with a configurable severity threshold and a per-deploy report in the UI; block only when an operator sets a threshold. Bake the advisory DB into the scanner image, refresh daily, expose last-sync time.
- **Dependencies:** none.
- **Status: Deferred — not implemented.**

## F08 — Alert digests and quiet hours

- **Value:** Alerts are immediate-only; operators are paged for every transient restart. Digests were explicitly deferred in `docs/entrega-3-historias-de-usuario.md:53`.
- **Effort / layer:** S–M · backend + frontend.
- **Approach:** Daily/weekly digest schedules and per-team quiet hours on top of the existing alert + dedup system. `daily_digest`/`weekly_summary` preference values already exist but are skipped by the alert service and have no UI. Use a per-user timezone with UTC fallback; suppress empty digests.
- **Dependencies:** none.
- **Status: Deferred — not implemented.**

## F12 — Deploy rollback / redeploy previous version

- **Value:** Deployment history and diff exist but cannot be applied, so recovery from a bad deploy is manual.
- **Effort / layer:** M · backend + frontend.
- **Approach:** A "Redeploy" action on a history entry that reconstructs the recorded config from the encrypted `DeployConfig` snapshot and starts a new deploy. A rollback is a new history entry with a `rollback_of` pointer. Fail fast with an actionable error when the original image tag no longer exists; offer "rebuild from recorded Git source" where applicable. Keep secrets redacted via F14.
- **Dependencies:** F13 (config update path), F14 (secret references).
- **Status: Deferred — not implemented.**

## F16 — Volume-upload management endpoint

- **Value:** Users can upload up to 150 MB of volume files but cannot list or delete them, so the quota can only be reclaimed by deleting the container.
- **Effort / layer:** S · backend + frontend.
- **Approach:** `GET`/`DELETE /api/containers/volume-uploads` with the same per-user ownership checks as upload, plus a UI list. Refuse deletion while any container references the upload (409 naming the container); allow force-delete only for admins. Upload hardening (streaming limits, atomic per-user quota lock, path containment) already landed.
- **Dependencies:** none.
- **Status: Deferred — not implemented.**

---

## Cross-cutting note: dependency vulnerabilities

`npm ci` reports 16 vulnerabilities (7 moderate, 9 high) from the locked dependency tree, including deprecated `xterm`/`xterm-addon-fit`. Triage (safe lockfile-only fixes vs explicit bumps, keeping `package.json` on exact versions) is tracked with defect remediation, not as a product feature. Requires the owner-supplied `npm audit --json` output or authorisation to run it.
