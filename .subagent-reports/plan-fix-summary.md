# Plan fix summary — docs/plans/2026-11-20-defect-remediation.md

All 27 audit findings (H-1…H-5, M-1…M-13, L-1…L-9) were re-verified against the cited source files. **27 fixed or folded, 0 rejected.** Plan-only edits: no source/infra files changed, no implementation run.

## High

- **H-1** (snapshot lookup by policy name): **fixed** in Task 4. Added `_base_container_info(orchestrator, base_name)` to resolve the policy name to the live container's Docker id; `_evaluate_policy` now passes `base_info.id` to `load_deploy_config_snapshot` (which still filters `DeploymentRecord.container_id`, matching `containers.py:395`). Added a test asserting `_base_container_info` returns id `cid-real` and that lookup by name `"api"` misses; expected count 2→3.
- **H-2** (unpinned Clerk script): **fixed** by folding into Task 10. New exported `CLERK_JS_VERSION` + `clerkBrowserScriptUrl()` replace `LoginPage.tsx:93` `@latest`; test asserts exact `@x.y.z` and no `@latest`; version is a concrete planned pin (`5.97.0`) with a single bump point.
- **H-3** (Compose interpolation in Traefik dynamic config): **fixed** in Task 14. `traefik/static/spa.yaml` now uses `{{ env "VELA_PUBLIC_HOST" }}` / `{{ env "VELA_TRAEFIK_ACME_RESOLVER" }}` for `main`, redirect rule and `certResolver`; defaults supplied as real env vars on the traefik Compose service. Step 1 rejects any `${...}` in that file.
- **H-4** (nonexistent file path): **fixed** in Task 11. All three occurrences changed to `frontend/src/components/DockerfileTemplatesSection.tsx` (Files, Step 3, commit).
- **H-5** (WS-ticket test): **fixed** in Task 7. Test now seeds a container via `fake_orchestrator.seed_container` with `vela.project_id` label and asserts anonymous → 401 plus authenticated → 200.

## Medium

- **M-1** (reports claimed absent): **fixed**. Global constraint, Task 9/10 Self-review notes and the final caveat now state the three reports are present in `.subagent-reports/`; "best-effort" downgrades removed.
- **M-2** (Node CI pin): **fixed** in Task 15. `node-version: "20"` in both the existing `e2e` job and the new `lint-and-typecheck` job, matching `frontend/Dockerfile:1` (`node:20-alpine`); gate asserts no `"22"` and at least two `"20"` pins.
- **M-3** (M15 URL sync, header-only): **fixed** with concrete steps in Task 12 for AdminPage `?tab=` and ResourceDashboard `?range=` using `useSearchParams`.
- **M-4** (L10 locale omissions): **fixed** in Task 10 with explicit `Intl.DateTimeFormat('en-US', …)` at `AuditLogPage.tsx:95` and `MetricChart.tsx:61,115` (L10 removed from Task 12 header).
- **M-5** (L5 skeletons, header-only): **fixed** in Task 11 with the shared `Skeleton` component at the four cited locations.
- **M-6** (L7/L8/L9/L14 header-only): **fixed**. L6/L14 given concrete steps in Task 10; L7/L8/L9 given concrete steps in Task 12. Render-phase ref assignment moved out of Task 10 entirely (Task 12 solely owns `ContainersPage`).
- **M-7** (L17 JSDoc, header-only): **fixed** in Task 12 with an explicit file/line list from `review-frontend.md`.
- **M-8** (PAT throttle 429s existing tests): **fixed** in Task 7. Added `backend/tests/conftest.py` autouse fixture calling `rate_limit.reset_for_tests()` / `ws_tickets.reset_for_tests()`; counted ~10 existing token POSTs.
- **M-9** (Task 10 vs 12 poll conflict): **fixed**. Task 10 no longer edits `ContainersPage.tsx` or claims L7; all poll/ref work consolidated in Task 12. Self-review records the nuance with evidence (assignment originates at `ContainersPage.tsx:126`).
- **M-10** (Gemini default / gate reads only README): **fixed** in Task 16. Gate now checks README, `.env.example` and `provider.py`; asserts exactly one `VELA_GEMINI_MODEL` row equal to `gemini-3.1-flash-lite`; Step 3 explicitly changes `.env.example:135`.
- **M-11** (undocumented LLM env vars): **fixed**. Task 14 documents `VELA_LLM_ALLOW_PRIVATE_ENDPOINTS` and `VELA_LLM_CACHE_DIR` (plus other infra vars) in `.env.example`; Task 16 gate checks them.
- **M-12** (no explicit ID in audit text — corresponding described issue: nginx body-limit alignment): **fixed** in Task 14 with a concrete Compose entrypoint that renders `client_max_body_size` from `VELA_VOLUME_UPLOAD_MAX_BYTES` at container start; the "keep 105m with a comment" choice was removed.
- **M-13** (WS-ticket E2E test has no container): **fixed** in Task 12. Test seeds a running container via `deployImageContainer` from `api-helpers.ts`, clicks terminal on that container's row and waits with `expect.poll`.

## Low

- **L-1** (placeholder `... # unchanged body`): **fixed** in Task 8 by writing the full `validate_outbound_url` body.
- **L-2** (vague setTimeout cleanup instruction): **fixed** in Task 10 with the concrete `highlightTimer` ref + `scheduleHighlight()` covering `StackBuilderPage.tsx:185,368`.
- **L-3** (incomplete Files lists): **fixed** — `test_admin_gates.py` in Task 1; `ContainersPage.tsx` removed from Task 10 (moved to Task 12); `containers.py`, `settings.py`, `test_runtime_config.py`, `app.test.tsx` added to Task 13; Task 11/12 file lists completed.
- **L-4** (nginx alignment): **fixed** in Task 14 (see M-12) — Go-template/Traefik fix and runtime nginx rendering are concrete, not left as an open decision.
- **L-5** (vague "Scan the modified forms"): **fixed** in Task 11 by replacing it with explicit M11/M12/L1/L4/L5/L11/L12 file-and-line edits.
- **L-6** (vague "6 passed (or current count)"): **fixed** in Task 1 to the exact `2 passed`.
- **L-7** (three alternatives for `git_branch`): **fixed** in Task 13 — deterministic one-line `delete body.git_branch`, no `analyze-source` call from deploy.
- **L-8** (useTheme unguarded write): **fixed** in Task 12 with a `try/catch` around `localStorage.setItem`.
- **L-9** (nginx/env-doc drift and CLI exec cap): **fixed** — CLI now reads the new real `GET /api/runtime-config` endpoint added in Task 13 (the speculative `/api/settings` field was removed); Task 14 documents all missing env vars; Task 16 makes the Gemini default single and consistent.

## Other explicitly requested checks

- WS-ticket backend test seeds via existing fixture **and** asserts anonymous rejection (Task 7) — done.
- PAT throttle does not 429 existing token tests (Task 7 conftest) — done.
- Node CI pin matches production image 20 (Task 15) — done.
- `.env.example` Gemini default single/consistent (Tasks 14/16) — done.
- No header-only tasks; 16 tasks kept in spec order, each with Files/Interfaces and TDD steps; Self-review table updated with folded items and audit disposition — done.

**Rejected findings:** none. **Remaining risk:** the Clerk pin version is a concrete planned literal that the implementer must confirm resolves against their Clerk account before bumping the single constant; the Traefik template rendering and nginx entrypoint are verified only by the plan's `docker compose up` infra gate, not by a source-level unit test.
