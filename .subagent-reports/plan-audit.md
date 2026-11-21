# Plan audit — docs/plans/2026-11-20-defect-remediation.md

Read-only audit against the approved spec, the three evidence reports (now present in this worktree), and AGENTS.md. All plan line numbers refer to the file as committed in this worktree. Source file/line references are from the same worktree at the plan's stated baseline.

## Verdict

**Needs fixes before execution.** All 16 spec units have a nominal task, but several spec decisions have no implementing step, one new backend lookup is guaranteed to disable scaling, two test steps cannot pass as written, one file path does not exist, and the Traefik/Node CI changes are self-contradictory.

Severity tally: **High 5 · Medium 13 · Low 9** (27 findings).

- High: H-1 … H-5
- Medium: M-1 … M-13
- Low: L-1 … L-9

---

## 1. SPEC COVERAGE

### 1.1 Unit → task map

| Spec unit | Task | Covered at unit level? |
|---|---|---|
| 1 Router auth/gates/test/audit | 1 | Yes |
| 2 Traefik backtick guard | 2 | Yes |
| 3 Stack delete auth ordering | 3 | Yes |
| 4 Replica runtime config | 4 | Nominally yes, but implementation is broken (H-1) |
| 5 Upload reads/quotas/containment | 5 | Yes |
| 6 PAT lifecycle + migration | 6 | Yes |
| 7 Auth hardening | 7 (+9 for log WS timeout) | Yes, but test defect H-5 / throttle risk M-8 |
| 8 Git SSRF + docs | 8 | Yes |
| 9 Backend cleanup | 9 | Yes |
| 10 Frontend correctness | 10 | Partial — M13/L7/L8/L9/L14 in header only (M-3, M-6) |
| 11 Frontend a11y/UX | 11 | Partial — L5 in header only (M-5) |
| 12 Frontend structure | 12 | Partial — M15/L17 in header only; L10 partial (M-4, M-7, L-8) |
| 13 CLI correctness/TUI/tests | 13 | Yes, with Files-list omission (L-3) |
| 14 Infra defaults/bind/edge/TLS | 14 | Partial — wrong Traefik syntax (H-3), nginx/LLM-doc drift (L-4, M-11) |
| 15 CI paths/jobs | 15 | Partial — Node not actually pinned to image version (M-2) |
| 16 Documentation drift | 16 | Partial — Gemini default/.env.example not corrected (M-10, M-11) |

### 1.2 Spec decisions with NO task (all verifiable against spec text)

| Decision | Spec line | Why uncovered |
|---|---|---|
| **Pin Clerk browser script `LoginPage.tsx:93` to a fixed version (H2)** | 46 | No task header or step mentions `clerk.browser`, pinning, or `LoginPage.tsx:86-104`. Task 10 owns `Home.tsx`/`core.ts`/`AuditLogPage`; Task 11 owns `Layout`/`UserMenu`/`AdminPage`/`Stacks`; Task 12 owns `Home`/`useTheme`/WS. Supply-chain security decision dropped entirely. |
| M13 — CSV export must use the same debounced search the table displays | 52 | Task 10 header (line 1400) lists M13, but Step 3 (1430-1446) never touches `LogsPage.tsx:132`; the only new test covers `formatApiError`. `debounced` appears nowhere in the plan (grep confirmed). |
| M15 — sync Admin tab / ResourceDashboard time-range to URL | 52 | Task 12 header (1547) lists M15; Step 3 (1583-1617) has no URL-sync change. `useSearchParams` appears only as a Task 10 "consumes" note (1408). |
| L5 — replace plain "Loading…" with skeletons | 52 | Task 11 header (1454) lists L5; Step 3 (1489-1539) never edits `StackBuilderPage.tsx:309`, `SettingsPage.tsx:193-194` or `RequireAuth.tsx:16`. |
| L7/L8/L9/L14 (spec unit 10 "timers, lifecycle, refresh") | 74 (unit table) | Task 10 header (1400) lists L6–L9 and L14; Step 3 only partially handles L6. `historyRefreshSignal`, the `ContainerTerminal` dispose leak, and the `useTheme` unguarded write appear nowhere in the plan's implementation steps. Worse, line 1446 tells the implementer to keep using `refreshRef.current()`, perpetuating the render-phase ref assignment (L7). |
| L17 — remove JSDoc noise | 52 | Task 12 header (1547) lists L15–L17; Step 3 only does PlaceholderPage + unused exports (1617). `JSDoc` appears nowhere else (grep confirmed). |
| L10 — explicit `Intl.*` locale for *all* timestamps | 52 | Task 10 handles `AuditLogPage:307` and `LogsPage:294` (1445) but omits `AuditLogPage:95` and `MetricChart.tsx:61,115` from the review inventory. |
| nginx `client_max_body_size` aligned with the configurable app limit | 57 | Task 14 line 1814 explicitly chooses "keep 105m with a comment", which does not satisfy alignment when `VELA_VOLUME_UPLOAD_MAX_BYTES` is raised above 105 MB (the exact drift B2 flags). |
| Add the two undocumented env vars from backend doc drift (`VELA_LLM_ALLOW_PRIVATE_ENDPOINTS`, `VELA_LLM_CACHE_DIR`) | 59 | Tasks 14/16 document only `VELA_GIT_ALLOW_PRIVATE_ENDPOINTS`, `VELA_PUBLIC_HOST`, `VELA_API_CONTAINER_USER` (1815, 1938, 1954). `.env.example` still contains neither LLM var (grep confirmed). |
| Correct the three conflicting Gemini model defaults | 59 | `.env.example:135` is still `VELA_GEMINI_MODEL=gemini-2.0-flash`. Task 16's gate (1937) only scans README, and Step 3 (1953) only edits README, so the third conflicting default survives. |
| Raise CLI `exec` cap to the server's `VELA_EXEC_MAX_SESSION_SECONDS` | 56 | Task 13 (1723-1730) reads a speculative `/api/settings.exec_max_session_seconds` and falls back to 3600. No backend task exposes that field, so the value is effectively a new hard-coded 3600, not the server setting. |

### 1.3 Note about the evidence reports

Plan lines 23, 1993 and 2002 repeatedly state the three evidence reports are "absent from this worktree" and downgrade F19/F20/F21, L2/L8/L9/L14, M13 and CLI A1.x to "best-effort". **They are present** (`.subagent-reports/review-backend.md`, `review-frontend.md`, `review-cli-infra-product.md`). This invalidates the plan's provenance caveat and explains several of the coverage holes above — see M-1.

---

## 2. PLACEHOLDER SCAN

Literal placeholder terms (`TBD`, `TODO`, `implement later`, `fill in`, `add appropriate`, `similar to`, `write tests for the above`) produced **zero** hits. Three "describes what to do without showing code/commands" hits, plus two borderline cases:

| Line | Hit | Assessment |
|---|---|---|
| 1204 | `...  # unchanged body` inside the `validate_outbound_url` rewrite | Placeholder. The existing body is not shown, so an implementer cannot tell which args/labels must be preserved when adding `allow_private_env`; the surrounding function is the SSRF guard being modified. |
| 1446 | `search the file for setTimeout in row-busy handlers and add return () => clearTimeout(handle)` | Vague instruction instead of code; also conflicts with Task 12 (M-9). |
| 1539 | `Scan the modified forms for missing <label htmlFor> and missing role=... and fix in place` | Unbounded sweep, no file/symbol list, no acceptance criterion; L1/L11/L12 labels already claim dedicated coverage. |
| 1721 | `...or, when values.branch is absent, call POST /api/builder/analyze-source ... Keep this one-line-simple: omit the key` | Presents three alternatives then picks one in prose; pick the one-line version explicitly so the diff is deterministic. |
| 1814 | `mount nginx.conf as a template or keep 105m with a comment` | Leaves an unresolved decision that determines whether the spec decision at line 57 is met (L-4). |

---

## 3. TYPE / SIGNATURE CONSISTENCY

Most cross-task names are internally consistent. Verified-good: migration chain `0022_api_tokens` (actual head) → `0023_deploy_config_snapshot` → `0024_api_token_lifecycle` (plan 501-509, 811-819); `client_identity`/`check_rate_limit`/`reset_for_tests` (1021-1047, 993/1064); `issue_ws_ticket`/`consume_ws_ticket` and their `logs|exec` purpose values (947-985, 1105-1142, 1587-1596); `require_container_access(..., action="read"|"write")` matches the keyword-only signature at `core/projects/access.py:58-65`; `get_user_by_id` is already imported in `containers.py:57`; `MintedApiToken.plaintext/prefix/token_hash` (768, 862-864) match `api_tokens.py:19-24`; `ApiTokenCreated` extends `ApiTokenPublic` so the new inherited fields work (923-928); `LlmConfig` really has `url` and `base_url` (1335 vs `provider.py:16-23`); `AccessTokenClaims` gains `issuer`/`audience` consistently with the test (1000, 1085); `formatApiError(error, locale?)` matches `core.ts:142-145`; `DockerfileTemplatesSection` is imported as a component (1523) but at the wrong path (H-4).

Mismatches / defects:

- **H-1 (function contract)**: `load_deploy_config_snapshot(session, container_id)` filters `DeploymentRecord.container_id` (plan 527-530), but Task 4 passes it `base_name` (556), which is `policy.container_name` (`scaling_engine.py:233`), while snapshots write `container_id=info.id` (`containers.py:395`). Name ≠ Docker ID.
- **H-3 (config format)**: `${VELA_PUBLIC_HOST:-...}` / `${VELA_TRAEFIK_ACME_RESOLVER:-...}` (1776, 1812) use Compose/CLI interpolation syntax in `traefik/static/spa.yaml`, a dynamic file-provider config (Traefik dynamic configs use `{{ env "VAR" }}` Go templates). The values will be treated as literal host/resolver names or rejected.
- **M-2 (constant drift)**: `node-version: "22"` is hard-coded in the new `lint-and-typecheck` job (1879) while `frontend/Dockerfile:1` is `node:20-alpine`; step 1861 only conditionally changes the existing jobs. B1.4 remains half-fixed even if 1861 is followed.
- **M-8 (shared-state leak)**: `check_rate_limit(client_identity(request))` added to `create_token` (1089) uses a module-global `_buckets` keyed by a constant test-client IP; only Task 7's own tests call `reset_for_tests()` (993, 1064). There are already 10 `POST /api/tokens/` calls across `test_api_tokens.py` (8), `test_exec_websocket.py:307` and the new `test_token_lifecycle.py:783`; the 11th returns 429. No reset hook is wired into conftest.
- **M-10 / M-11 (docs)**: `.env.example:135` still `gemini-2.0-flash`; no `VELA_LLM_ALLOW_PRIVATE_ENDPOINTS` / `VELA_LLM_CACHE_DIR` rows. Task 16's self-gate (1937-1942) cannot catch either.
- **L-3 (Files lists)**: `test_admin_gates.py` created at 78 but not listed at 30; `ContainersPage.tsx` edited at 1446 but absent from Task 10's Files (1402-1405); `backend/app/api/routes/containers.py` edited at 1738 and committed at 1752 but absent from Task 13's Files (1627-1630).
- **L-6 (vague expected count)**: "Expected: `6 passed` (or current count)" (257) while only two tests are added at 38-95.

---

## 4. TASK SOUNDNESS

Verified runnable/good: all backend test commands use the correct `cd backend` + CI env vars per AGENTS.md (17); frontend commands match `frontend/package.json` scripts (18); CLI commands match `cli/package.json` + AGENTS.md (20); all cited conftest fixtures exist (`fake_orchestrator:126`, `db_session_factory:173`, `seeded_user:269`, `seeded_other_user:282`, `api_client:364`, `other_user_client:381`, `anonymous_client:398`); `update_scaling_policy` exists (`scaling.py:86`); `E2E_ADMIN_EMAIL/PASSWORD` and `loginAndSeedToken` are exported (`constants.ts:10-11`, `fixtures.ts:30`); `.hero__eyebrow` exists (`Home.tsx:33`); `STORAGE_KEY` exists (`useTheme.ts:5`); migrations `0023/0024` chain from the real head; Task 15's `http://127.0.0.1:8081/api/health` matches `${VELA_WEB_PORT:-8081}` (`docker-compose.yml:102`, `.env.example:59`); `backend/app/bootstrap_env.py` and `create_app` (`app.py:124`, with the `bootstrap_env` import at line 5) exist. `api_client` etc. are used with the correct cwd in every step.

Tasks that would fail immediately or leave a non-committable/incorrect state:

- **H-4 Task 11 (lines 1457, 1523, 1543)**: `frontend/src/pages/DockerfileTemplatesSection.tsx` does not exist. The component is `frontend/src/components/DockerfileTemplatesSection.tsx` (imported that way by both `BuilderPage.tsx:4` and `ImagesPage.tsx:4`). `git add` of the listed path fails; editing it creates a stray duplicate that is never imported, so template deletion stays unfixed.
- **H-5 Task 7 (lines 988-990)**: `test_ws_ticket_endpoint_requires_auth` posts to `/api/containers/cid-1/ws-ticket` with no container seeded. The endpoint calls `require_container_access` (1116-1119) → `orchestrator.get("cid-1")` → `ContainerNotFoundError` (`fake_orchestrator.py:240-242`) → 404, not 200. Also the test name claims to assert anonymous rejection but only uses the authenticated `api_client`.
- **H-1 Task 4 (556)**: as above — snapshot lookup by name always misses, so `_evaluate_policy` takes the `base_config is None → log and return` path (558) and scaling never scales up.
- **M-13 Task 12 (1570-1578)**: the WS-ticket E2E test clicks a "terminal" button on a fresh `/containers` page without deploying any container; unlike `e2e/terminal.spec.ts` (which deploys first), there is no seeded running container, so the button/ws never appears. Will time out.
- **M-5/M-3/M-4/M-6/M-7**: tasks whose headers promise findings their Steps never implement — the reviewer per task has no acceptance criteria for those items and the final commit still ships the defects.
- **L-2/L-3**: placeholder instructions and incomplete Files lists mean the per-task "one implementer + one reviewer" gate in AGENTS.md cannot reliably verify the intended diff.

---

## 5. ORDERING / DEPENDENCIES

- Migration order is correct: Task 4 (`0023`) before Task 6 (`0024`, `down_revision = 0023_deploy_config_snapshot`), both before Tasks 14-16's final gates. Verified `0022_api_tokens` is the actual head.
- Auth/WS-ticket sequencing across layers is correct: Task 7 introduces the backend `POST /api/containers/{id}/ws-ticket` endpoint (1105-1120) and ticket-based WS auth (1122-1143); Task 9 retains the log-stream timeout; Task 12 consumes the endpoint in the frontend (1555, 1583-1598). Task 7's `frontend/playwright.config.ts` edit adding `VELA_ALLOWED_ORIGINS` (1101) precedes Task 11/12 E2E runs.
- **M-9 ordering conflict**: Task 10 (1446) edits `ContainersPage.tsx` success handlers to use `refreshRef.current()` and says "keep the single discovery poll loop at lines 88-95"; Task 12 (1615) then *moves that same interval out* of `ContainersPage` into `useActiveDeployJobs` and removes the page-level interval. Implemented sequentially, Task 12 rewrites/obsoletes Task 10's edit and the two tasks' reviewers will disagree about the source of truth. Consolidate into Task 12 only, and drop lines 1400/1446's L6/L7 claims.
- **M-2**: Task 15's CI change must be planned against `frontend/Dockerfile:1` (node:20-alpine) and must update *both* the existing `e2e` job and the new `lint-and-typecheck` job; as written it pins only one.
- **L-4/H-3**: Task 14 must be completed (including the Traefik syntax fix) before Task 15's `infra-smoke` job and Task 16's final gate can meaningfully pass.
- Merge notes for Tasks 7/8/13/14 are present and consistent with the spec's five-commit caveat (2002), but the reports being available (M-1) means several "best-effort" merge resolutions could have been specified exactly.

---

## 6. TOP ACTIONABLE DEFECTS (ranked)

1. **H-1** — Task 4 line 556 looks up the deploy snapshot by container **name** while the column stores the Docker **ID** (`containers.py:395`, `scaling_engine.py:233`). Auto-scaling will silently stop scaling up. Fix: look up by `DeploymentRecord.container_name` (add that filter to `load_deploy_config_snapshot`) or resolve name→ID first; add an assertion in `test_replica_config.py` for the name-based lookup.
2. **H-2** — Spec decision at line 46 to pin the Clerk browser script (H2, supply-chain) has **no task**. Add it to Task 10 or 12 with a concrete pinned version and `LoginPage.tsx:93`.
3. **H-3** — Task 14 lines 1776/1812 put Compose-style `${VAR:-default}` in Traefik **dynamic** config (`traefik/static/spa.yaml`); use `{{ env "VELA_PUBLIC_HOST" }}` / `{{ env "VELA_TRAEFIK_ACME_RESOLVER" }}` with static defaults, else TLS domain/resolver drift.
4. **H-4** — Task 11 lines 1457/1523/1543 use nonexistent `frontend/src/pages/DockerfileTemplatesSection.tsx`; real path is `frontend/src/components/DockerfileTemplatesSection.tsx`.
5. **H-5** — Task 7 lines 988-990 expect 200 from a WS-ticket request for an unseeded container; it returns 404. Seed a container first (as Task 3 does) and add an anonymous → 401 assertion.
6. **M-8** — PAT throttling (1089) will 429 existing token tests (10 already POST `/api/tokens/`); add a conftest autouse reset or exclude authenticated PAT creation from the limiter.
7. **M-2 / M-10 / M-11** — CI still pins Node 22 in the new job; `.env.example` keeps `gemini-2.0-flash` and omits the two LLM env vars. Tighten Task 15/16 gates to check these files too.
8. **M-3/M-4/M-5/M-6/M-7** — Tasks 10-12 headers claim M13, M15, L5, L7-L9, L14, L17 but their steps don't implement them; either add concrete steps or remove the claims from headers and Self-review (1983-2000).
9. **M-9** — Task 10 vs Task 12 poll-loop conflict; consolidate to Task 12.
10. **M-13** — Task 12 WS-ticket E2E test needs a deployed container.

---

## 7. VERDICT

All 16 units are mapped, but the plan is **not ready to execute**: one guaranteed functional regression (H-1), one dropped security decision (H-2), one wrong config syntax (H-3), one nonexistent path (H-4), two tests that cannot pass (H-5, M-13), and a set of header-only "coverage" claims. Fix High findings first, then the Medium coverage/test items, then rerun this audit.
