# Task 7 Report: Frontend types + shared BuildConfigModal

**Status:** DONE  
**Commit:** _(pending)_ — feat: shared BuildConfigModal for manual language overrides  
**Date:** 2026-08-11

## Summary

Added `BuildOverride` client types (preserving existing `git_branch` / `parseCompose` WIP), a type-guard helper for `needs_build_override` API errors, and a shared `BuildConfigModal` that reuses stacks-modal CSS. ContainersPage / Stacks wiring deferred to Tasks 8–9.

## Changes

### `frontend/src/api/client.ts`

- `BuildOverrideLanguage` + `BuildOverride` matching backend
- `RunFromSourceRequest.build_override`
- `GitSourceAnalysis.build_subdir` + `needs_manual_build_config`
- `DeploymentRecord` / `StackService` / `StackServiceCreate.build_override`
- Preserved uncommitted `git_branch` on stack service types and `parseCompose`

### `frontend/src/pages/containers/buildOverride.ts`

- `isNeedsBuildOverrideError` via `code` on parsed API error body (type guards, no `instanceof`)
- Language / package-manager helpers with exhaustive `never` switches
- Defaults for version and package manager; start-command parse/format

### `frontend/src/pages/containers/BuildConfigModal.tsx`

- Props: `open`, `onCancel`, `onConfirm(override)`, optional `initial`
- Language select; package manager for java / js|ts / clojure
- Optional version, build subdirectory, start command
- Escape / backdrop cancel; focus restore (ComposeImportReviewModal pattern)

### `frontend/src/index.css`

- Reused `.stacks-modal*` patterns; added `.stacks-modal--build-config` narrow variant

## Build

```
cd frontend && npm run build
```

Result: pass (`tsc -b && vite build`)

## Notes

- Staged only Task 7 frontend files (+ needed `client.ts` / modal CSS). No ContainersPage or Stacks wiring.
- `index.css` includes stacks-modal base styles required by the shared modal (same patterns as compose-import review).
