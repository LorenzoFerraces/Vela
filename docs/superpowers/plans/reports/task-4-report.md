# Task 4 Report: Image builder + stack deploy pass override / build_subdir

**Status:** DONE  
**Commit:** (pending) — feat: honor build override and subdir in image builds  
**Date:** 2026-08-11

## Summary

Wired `BuildOverride` through `ImageBuilder.build_from_source` and `DefaultImageBuilder`, so Docker builds use the effective `build_subdir` (with `is_relative_to` path traversal checks). Stack git deploys parse `service.build_override` JSON into `BuildOverride` and pass it into the builder. `FakeContainerOrchestrator` now records build-context paths for assertions.

## TDD Workflow

1. **Failing tests written** — `backend/tests/test_default_image_builder_override.py` (nested subdir context, override subdir, invalid `../` rejection, deploy JSON → override pass-through).
2. **Initial run** — nested built from repo root; `override=` TypeError; deploy passed `override=None`.
3. **Implement** — protocol + DefaultImageBuilder + deploy helper + fake path recording.
4. **Final run** — 4/4 new tests pass (16 with related override/ensure suites).

## Changes

### `backend/app/core/build/builder.py`

- `build_from_source(..., override: BuildOverride | None = None)` on the ABC.

### `backend/app/core/build/default_image_builder.py`

- Forwards `override` to `ensure_dockerfile_for_build`.
- Resolves `info.build_subdir` safely; builds from that directory; snapshots Dockerfile from the effective root.

### `backend/app/core/stacks/deploy.py`

- `_build_override_from_service` via `getattr(service, "build_override", None)` + `BuildOverride.model_validate`.
- Git branch of `_resolve_service_image` passes `override=` into the builder.

### `backend/app/core/containers/fake_orchestrator.py`

- Records `_built_paths` on each `build_image` call.

### Tests

- `backend/tests/test_default_image_builder_override.py`

## Test Results

```
f:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests/test_default_image_builder_override.py tests/test_ensure_dockerfile.py tests/test_build_override_model.py -q
16 passed, 1 warning in 0.10s
```

## Self-Review

| Check | Result |
|-------|--------|
| Nested marker → build context = subdir | ✓ |
| Override `build_subdir` honored | ✓ |
| Path traversal rejected (`is_relative_to`) | ✓ |
| Stack deploy parses JSON override | ✓ |
| Fake orchestrator records paths | ✓ |
| Only Task 4 files committed | ✓ |

## Concerns

- `StackService.build_override` column lands in Task 5; deploy uses `getattr(..., None)` so missing attribute is safe until then.
- Containers run-from-source API still does not pass override (Task 6).
- Invalid subdir may raise from `ensure_dockerfile_for_build` before the builder’s second check; both raise `AnalysisError`.
