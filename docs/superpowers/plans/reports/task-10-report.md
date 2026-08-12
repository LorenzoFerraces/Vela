# Task 10 Report: E2E coverage for build override modal

**Status:** DONE  
**Commit:** `5b3ecf8` — test: e2e for build override modal on stacks/containers  
**Date:** 2026-08-11

## Summary

Added Playwright coverage for the shared BuildConfigModal on Containers and Stacks. Extended E2E stubs so analyze/build never hit real GitHub: empty-clone under `VELA_E2E=1`, and analyze on branch `needs-manual` returns `needs_manual_build_config`.

## Changes

### `frontend/e2e/build-override.spec.ts`
- Containers: Build git `org/repo` → `needs_build_override` modal → Java / Gradle → assert deploy Started
- Stacks: Analyze with branch `needs-manual` → modal → save override → persist → Edit → reopen service → assert override text

### `backend/app/e2e_support.py`
- `E2E_NEEDS_MANUAL_BRANCH = "needs-manual"` analysis fixture sets `needs_manual_build_config=True`
- `e2e_git_shallow_clone_if_enabled` creates an empty dest (no markers) so override generation / `needs_build_override` work under FakeContainerOrchestrator

### `backend/app/core/git/git_ops.py`
- Prefer E2E empty-clone stub when `VELA_E2E=1`

## E2E

```text
cd frontend && npm run test:e2e -- e2e/build-override.spec.ts
# 2 passed
```

## Notes / concerns

- Existing analyze E2E for `org/repo` + `main` unchanged (still Vite port 5173 fixture).
- Edit Stack hides the service form until the list item is selected; the spec clicks `.stacks-builder__list-item` before asserting override text.
