# Task 9 Report: Wire Stacks builder + list deploy

**Status:** Complete  
**Commit:** (pending) — feat: stacks persist and prompt for per-service build overrides  
**Date:** 2026-08-11

## Summary

Wired shared `BuildConfigModal` into the Stacks builder and list deploy flow. Git services can analyze / configure a per-service `build_override`, which persists through create/update. List Deploy opens the modal on `needs_build_override`, PATCHes the failing service, and redeploys. Stack deploy now re-raises `NeedsBuildOverrideError` (with service name in detail) so the typed client helper works.

## Changes

### `frontend/src/pages/stacks/StackBuilderPage.tsx`
- Git services: Analyze repo + Configure build open `BuildConfigModal`
- Seed modal from analyze when `needs_manual_build_config`
- Persist `build_override` on load/save; clear when leaving git source
- Preserved existing Close button and git_branch UI

### `frontend/src/pages/StacksPage.tsx`
- On deploy `needs_build_override`: parse failed service from detail, open modal
- Confirm → `updateStack` with override → redeploy (loops if another service needs config)

### `frontend/src/pages/containers/buildOverride.ts`
- Added `parseFailedServiceNameFromError` for `Deploy failed on service '…'` detail

### `frontend/src/pages/stacks/ComposeImportReviewModal.tsx`
- Optional muted note when an imported git service already has `build_override`

### `backend/app/core/stacks/deploy.py`
- After rollback cleanup, re-raise `NeedsBuildOverrideError` with service name in the message (otherwise list deploy only saw a generic HTTP 500)

### `frontend/src/index.css`
- `.stacks-builder__build-actions` layout for Analyze / Configure buttons

## Verification

```text
cd frontend && npm run build
# tsc -b && vite build — PASS
```

## Notes / concerns

- API types already included `StackService` / `StackServiceCreate.build_override` (Task 7); no client type change required.
- Without the deploy.py re-raise, stack deploy failures were wrapped as HTTP 500 without `code: needs_build_override`.
