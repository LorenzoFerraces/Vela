# Task 6 Report: API schemas, error handler, analyze enrichment, route wiring

**Status:** DONE  
**Commit:** (see git log) — feat: API support for build overrides and needs_build_override errors  
**Date:** 2026-08-11

## Summary

Wired `BuildOverride` through HTTP schemas and stack/container routes, mapped `NeedsBuildOverrideError` to HTTP 422 with `{code, detail}`, and enriched git analyze responses with `build_subdir` / `needs_manual_build_config`. Preserved in-tree `git_branch` + parse-compose WIP on schemas/stacks/tests while adding `build_override`.

## Changes

### `backend/app/api/schemas.py`

- `RunFromSourceRequest.build_override: BuildOverride | None`
- `BuilderBuildRequest.build_override: BuildOverride | None`
- `GitSourceAnalysis.build_subdir` + `needs_manual_build_config`
- `StackServiceCreate` / `StackServicePublic.build_override`
- `DeploymentRecordPublic.build_override`
- Kept existing `git_branch` + compose parse schema WIP

### `backend/app/api/errors.py`

- Dedicated `NeedsBuildOverrideError` handler → 422 + `exc.api_response_content()`

### `backend/app/api/routes/stacks.py`

- Create/update persist `build_override` JSON; `_stack_to_public` / `_orm_service_to_create` expose it
- Kept `git_branch` + parse-compose route WIP

### `backend/app/api/routes/containers.py`

- Git run passes `override=body.build_override` into `build_from_source`
- Deployment snapshot stores override JSON

### `backend/app/api/routes/builder.py`

- `/build` forwards optional `build_override`

### `backend/app/core/git/git_source_analysis.py`

- Fallback + Gemini paths set `build_subdir` / `needs_manual_build_config` from local marker scan

### `backend/app/core/deploy/deployment_history.py`

- `DeploymentSnapshot.build_override` persisted on `DeploymentRecord`

### `backend/tests/test_api_integration.py`

- `test_stack_create_persists_build_override`
- `test_run_from_git_needs_build_override`

## Tests

```
f:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest \
  tests/test_api_integration.py::test_stack_create_persists_build_override \
  tests/test_api_integration.py::test_run_from_git_needs_build_override \
  tests/test_api_integration.py -k "stack or run_from_git or deployment" -q
```

Result: pass (new cases + related stack/git suite)

## Notes

- Staged only backend API/core/test files for this task; frontend left unstaged.
- `git_branch` WIP in schemas/stacks/tests was retained and committed with build_override because the persistence test uses both fields.
