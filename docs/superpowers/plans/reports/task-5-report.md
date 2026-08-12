# Task 5 Report: DB migration for build_override

**Status:** DONE  
**Commit:** (see git log after commit)  
**Date:** 2026-08-11

## Summary

Added nullable JSON `build_override` columns on `StackService` and `DeploymentRecord`, and Alembic revision `0016_build_override` (down_revision `0015_stack_service_git_branch`). Also committed previously untracked `0015_stack_service_git_branch` plus the matching `StackService.git_branch` model field so the revision chain resolves.

## Changes

### `backend/app/db/models.py`

- `StackService.git_branch` (from unfinished 0015 WIP)
- `StackService.build_override: Mapped[dict | None]`
- `DeploymentRecord.build_override: Mapped[dict | None]`

### `backend/alembic/versions/0015_stack_service_git_branch.py`

- Adds nullable `git_branch` String(256) on `stack_services` (was untracked; already applied locally before this task).

### `backend/alembic/versions/0016_build_override.py`

- Adds nullable `build_override` JSON on `stack_services` and `deployment_records`.

## Alembic

```
Running upgrade 0015_stack_service_git_branch -> 0016_build_override
current/heads: 0016_build_override
```

## Notes

- Staged only migration + models persistence files; left frontend/stack-builder WIP unstaged.
- Dev Postgres was available; `alembic upgrade head` succeeded.
