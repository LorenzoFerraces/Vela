# Defect remediation — design spec

- **Status:** Approved 2026-11-20; implemented via docs/plans/2026-11-20-defect-remediation.md.
- **Branch/workspace:** `fix/review-defect-remediation`, an isolated worktree whose branch points at `dev` (`4b59b57`). This baseline deliberately does **not** contain the three commits that exist only on `fix/security-and-cli-hardening` (`c03fcbd` security hardening, `f1517bb` docstrings, `aad7943` Linux deploy fix). Those commits must be merged into this branch separately; this work neither reverts them nor re-applies their unrelated parts. One expected overlap: `aad7943` fixed the Linux volume-upload bind, so Unit 14 must implement an equivalent fix on this `dev` baseline — resolving the merge conflict later is acceptable.
- **Goal:** Fix every defect found in the full-project review — all findings in Waves A (security/correctness), B (medium bugs and frontend UX/a11y), and C (CLI, infra, CI, docs). Wave D (new features) is specified separately in `2026-11-20-platform-features-design.md` and is explicitly out of scope here.

## Source inventory

The detailed, evidence-backed findings live in three report files (written against the review checkout; every item below was re-verified against `dev` before approval):

- `.subagent-reports/review-backend.md` — F1–F27, feature gaps, coverage and doc drift.
- `.subagent-reports/review-frontend.md` — H1–H3, M1–M15, L1–L17, guidelines findings.
- `.subagent-reports/review-cli-infra-product.md` — A1.1–A1.7, B1.1–B1.4, B2–B4 (Part C is the feature spec's source).

Those reports are the inventory; this spec holds the decisions that constrain implementation.

## Decisions

### 1. Authentication and privilege boundaries

- Put `Depends(get_current_user)` at the **router level** for `traffic`, `images`, and `builder` (`backend/app/api/deps.py:176`). This covers every handler including GETs and prevents a future handler from being added without auth.
- Add a second, explicit **admin** gate (`deps.py:207`, `require_admin`) on host-level mutating endpoints: `POST`/`DELETE /api/routes`, `POST /api/images/pull`, `POST /api/images/build`, `POST /api/builder/build`, `POST /api/builder/analyze`. These touch the host Docker daemon and server filesystem, not a user's own workload; a logged-in student must not get them.
- `POST /api/builder/analyze-source` stays at the caller's own user scope: it is already bound to that user's GitHub token and drives deploy-form prefill.
- Do **not** add a compatibility escape hatch for anonymous callers. The SPA and CLI do not call these endpoints today; anonymous use is the defect being removed.
- Add one integration test that enumerates mounted routers and asserts every route except `/api/health` and the `/api/auth/*` login/config routes rejects an anonymous request. This is the regression guard for the whole class of bug.
- Emit audit events for traffic route changes, image pull/build, and PAT create/revoke (currently unaudited, F27), using the existing `emit_audit_log` mechanism.

### 2. Fix at the shared root, not at each caller

- **Traefik injection (F4):** `_path_rule` in `backend/app/core/traffic/traefik_file_traffic_router.py:48` must reject backticks exactly as `_host_rule` does at `:42`. Add a unit test with a prefix containing a backtick.
- **Stack delete authorization (F5):** extract a `require_stack_write_access(session, stack, user_id)` helper in `backend/app/core/stacks/repository.py`; call it from both `delete_stack()` (`:152`) and `delete_user_stack()` in `backend/app/api/routes/stacks.py:233` **before** the first Docker mutation. A viewer must receive 403 with containers and network still present. Test the persisted/Docker state, not just the status code.
- **Upload reads (F7):** enforce the byte limit while streaming in the shared upload path (`core/containers/volume_uploads.py` and `api/routes/users.py:57`), before buffering; never trust a client-declared size. Make quota accounting atomic enough that concurrent uploads cannot exceed the per-user/team caps; replace the string-prefix containment check at `volume_uploads.py:164` with `Path.is_relative_to`.
- **Error mapping (H1):** one `typeof detail === 'string'` guard in `frontend/src/api/core.ts:157` so FastAPI 422 object/array details can never reach React as children. Add a focused test.
- **Replica config (F6):** build replicas from the stored deploy configuration (env, command, limits, network, restart policy) rather than the lossy `ContainerInfo` shape in `core/scaling/scaling_engine.py:145`. If the deploy record does not retain those fields, extend it with a migration — do not silently default them away.
- **PAT lifecycle (F11):** add expiry, last-used-at, and scope columns to `ApiToken` with an Alembic migration; default existing rows to non-expiring to avoid breaking current tokens. Keep the CLI token flow working.
- **LLM cache (F18):** include user id, provider fingerprint and repo identity in the cache key so two users or two providers cannot share a private-repo analysis.
- **Scaling policy authorization (F26):** `PUT /api/scaling/policies/{name}` must require write access, not merely container visibility.

### 3. Other security/correctness decisions

- Login throttling (F8): keep the in-process limiter but key it on a trusted client identity when `FORWARDED_ALLOW_IPS` is configured, and add throttling to `/auth/clerk/exchange` and PAT creation. Document the multi-worker limitation rather than inventing a distributed store in this wave.
- Git clone SSRF (F10): reuse the existing outbound-URL guard (`core/security/outbound_url.py`) for Git URLs, with an explicit opt-in env var for private endpoints, mirroring `VELA_LLM_ALLOW_PRIVATE_ENDPOINTS`.
- Clerk exchange (F12): when Clerk is enabled, require the origin/`azp` allowlist rather than only warning; E2E fixtures must set it.
- WebSocket auth (F13, M7): accept and authenticate the connection before `websocket.accept()` on log streams; add the per-session timeout the exec socket already has. Replace the bearer token in the query string with a short-lived, single-use WS ticket issued by an authenticated endpoint (both frontend and CLI callers updated in the same change).
- JWT (F15): add `iss`/`aud` claims and verify them, keeping a single configured audience per deployment.
- Host-level config drift: remove the hardcoded `velaunq.ddns.net` default from CORS, `.env.example`, compose and Vite config; use neutral values. Pin the Clerk browser script (`LoginPage.tsx:93`) to a fixed version. Fail closed at startup when required secrets are blank (B1.3) with a clear message; do not invent insecure defaults.
- Instructor cross-project membership (F9): preserve the documented platform-instructor capability but emit audit events on member/invitation mutations and state the scope explicitly in the README.
- Container log-stream and exec paths keep their existing access checks; preserve safety-critical assertions on persisted state.

### 4. Frontend UX/a11y decisions (no new interaction models)

Follow existing repo patterns exactly: reuse `ConfirmDialog` for stack deletion and template deletion; add the skip link and labelled `main` in `Layout.tsx`; use `<Link>` for account-menu navigation; add arrow-key support to the admin tab widget; send audit dates as plain `YYYY-MM-DD` strings (no local-midnight → UTC conversion); use `Intl.*` with an explicit locale; keep skeletons as the loading pattern; sync tab/time-range state to the URL as Logs/Audit already do; export CSV using the same debounced search the table displays; guard navigation with unsaved changes in the stack builder; update `meta theme-color` on theme changes; make Home copy consistently English. Consolidate the three Containers poll loops to one source of truth. Deduplicate the Images and Builder pages into one shared page component. Remove dead code (`PlaceholderPage`, unused API exports) and JSDoc noise flagged by the review. Keep all changes inside the existing brutalist/token system — no new colors, radii or shadows.

### 5. CLI, infra, CI, docs decisions

- CLI: raise `exec`'s hard-coded 10-minute cap to the server's `VELA_EXEC_MAX_SESSION_SECONDS`; add bounded polling plus `--no-wait` to `run`; resolve container names against paginated results or an exact-name lookup; remove the dead `--server` flag path; stop hard-coding `git_branch: "main"` where inference is available; bound table column widths; make the TUI `l`/`e` keys work or remove them; add command-level tests for `waitForJob` and env parsing.
- Infra: use a named volume (or pre-created host dir) for volume uploads so a fresh Linux host does not create a root-owned bind; add HTTP→HTTPS redirect at the edge; gate the insecure Traefik dashboard behind an env flag; add a staging ACME resolver option; align nginx's `client_max_body_size` with the app limit; pin CI Node to the production image's version; pin Bun; document `VELA_API_CONTAINER_USER`; add resource limits/hardening to compose services.
- CI: add infra paths to the `paths` filters; add `ruff check`, `mypy`, frontend lint/typecheck/build, and a `docker compose config -q` + build smoke job; keep the existing pytest and Playwright suites.
- Docs: correct the README E2E section (live API + Vite, no `page.route`), the ownership model, Clerk endpoints, Traefik file name, and the three conflicting Gemini model defaults; add the two undocumented env vars. Keep the README concise.

## Implementation units (planning input, not yet committed to a plan)

| # | Unit | Covers |
|---|------|--------|
| 1 | Router auth, admin gates, route-level auth test, audit events | F1–F3, F27 |
| 2 | Traefik backtick guard | F4 |
| 3 | Stack delete auth ordering | F5 |
| 4 | Replica runtime config | F6 |
| 5 | Upload reads, quotas, containment | F7, F22, F23 |
| 6 | PAT expiry/last-used/scope + migration | F11 |
| 7 | Auth hardening: throttle, Clerk, JWT, WS auth/ticket | F8, F12, F13, F15, M7 |
| 8 | Git URL SSRF guard; outbound config docs | F10 |
| 9 | Backend cleanup: dead code, duplicate constants, cache key, log WS timeout, scaling write auth | F9, F18, F19, F20, F21, F26 |
| 10 | Frontend correctness (error mapper, dates, export, timers, lifecycle, refresh) | H1, M1, M13, L2, L6–L9, L14 |
| 11 | Frontend a11y/UX (dialogs, guards, tabs, links, live regions, forms, labels) | H3, M2–M5, M11, M12, L1, L4, L5, L11, L12 |
| 12 | Frontend structure/consistency (polls, WS ticket caller, dedup, locale, dead code, theme, copy, docs) | M6–M10, M14, M15, L3, L10, L15–L17 |
| 13 | CLI correctness, TUI, command tests | A1.1–A1.7, TUI, A.4 |
| 14 | Infra defaults, volume bind, edge/TLS, compose hardening | B1.1, B1.3, B1.4, B2, B3 (non-feature parts) |
| 15 | CI paths and jobs | B1.2, B4 |
| 16 | Documentation drift | README/env/spec drift items |

## Verification gate (every unit, before it is called done)

1. Backend: `python -m pytest tests -q`, `ruff check .`, `mypy app/ tests/` (CI env vars per `AGENTS.md`).
2. Frontend: `npm run build`, `npm run lint`, `npm run typecheck`, `npm run test:e2e`.
3. Infra: `docker compose -f docker-compose.yml config -q`, `docker compose up -d --build`, confirm `migrate` completed and `api` is `healthy` via `docker compose ps`, then `docker compose down`.
4. Deslop the unit's diff: remove unnecessary comments, abnormal `try`/`except` on trusted paths, type-silencing `any` casts, and structure that diverges from surrounding code — without changing behavior except for clear bugs.
5. Each unit is implemented by one subagent and reviewed by a second before the next unit starts (strictly sequential, per repo rules). Main session keeps the ledger and short status only.

## Explicit non-goals

- No new product features (Wave D) — those are specified, not built.
- No distributed rate limiter, secret store, Redis/Postgres job state, or HA work in this wave.
- No re-application of the security-hardening commits that live on the other branch; merge them separately.
