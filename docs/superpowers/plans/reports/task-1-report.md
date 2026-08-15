# Task 1 Report: Enum, BuildOverride, and NeedsBuildOverrideError

**Status:** DONE  
**Commit:** `0aa119c` — feat: add BuildOverride model and NeedsBuildOverrideError  
**Date:** 2026-08-11

## Summary

Added four new `SupportedLanguage` enum values, a `BuildOverride` Pydantic model for client-supplied build overrides, `NeedsBuildOverrideError` for detection-failure API responses, and `ProjectInfo.build_subdir` for monorepo subdirectory support.

## TDD Workflow

1. **Failing tests written** — `backend/tests/test_build_override_model.py` with three tests covering enum values, `BuildOverride` defaults, and error payload shape.
2. **Initial run** — `ImportError: cannot import name 'NeedsBuildOverrideError'` (expected).
3. **Implementation** — enum members, models, exception, and `__init__.py` re-exports.
4. **Final run** — `3 passed` in 0.03s.

## Changes

### `backend/app/core/enums.py`

Added to `SupportedLanguage`:

| Member   | Value      |
|----------|------------|
| `PHP`    | `"php"`    |
| `DOTNET` | `"dotnet"` |
| `ELIXIR` | `"elixir"` |
| `CLOJURE`| `"clojure"`|

### `backend/app/core/models.py`

- **`BuildOverride`** — new model before `ProjectInfo` with fields:
  - `language: SupportedLanguage` (required)
  - `language_version: str | None = None`
  - `package_manager: str | None = None`
  - `build_subdir: str | None = None`
  - `start_command: list[str] | None = None`
- **`ProjectInfo`** — added `build_subdir: str | None = None`

### `backend/app/core/exceptions.py`

- **`NeedsBuildOverrideError(BuilderError)`** — `code = "needs_build_override"`; `api_response_content()` returns `{"code": ..., "detail": str(self)}`.

### `backend/app/core/__init__.py`

Re-exported `BuildOverride` and `NeedsBuildOverrideError` alongside existing builder types.

### `backend/tests/test_build_override_model.py`

New test module (3 tests) as specified in the plan.

## Test Results

```
python -m pytest tests/test_build_override_model.py -q
3 passed, 1 warning in 0.03s
```

## Self-Review

| Check | Result |
|-------|--------|
| Enum string values match plan verbatim | ✓ |
| `BuildOverride` field types and defaults | ✓ |
| `ProjectInfo.build_subdir` optional default | ✓ |
| `NeedsBuildOverrideError` extends `BuilderError` | ✓ |
| `api_response_content()` shape | ✓ |
| `__init__.py` re-exports | ✓ |
| Only task files committed | ✓ (5 files) |
| Linter clean on changed files | ✓ |

## Notes for Later Tasks

- `UnsupportedProjectError` remains in the codebase; later detection work should raise `NeedsBuildOverrideError` where the client should show the override modal.
- `BuildOverride` is not yet wired into API routes or `ImageBuilder`; Task 2+ will consume it.
- No Dockerfile templates for PHP/DOTNET/ELIXIR/CLOJURE yet — enum values are preparatory.

## Concerns

None.
