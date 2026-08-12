# Task 3 Report: Dockerfile templates + ensure_dockerfile_for_build with override

**Status:** DONE  
**Commit:** `bb64712` — feat: Dockerfile templates for JVM, Clojure, and expanded languages  
**Date:** 2026-08-11

## Summary

Moved Dockerfile generators into `dockerfile_templates.py` and wired `ensure_dockerfile_for_build` to the override-aware resolution order from the design doc: existing Dockerfile never overwritten → override language wins → auto-detect generate → else `NeedsBuildOverrideError`. Added templates for Java (Gradle/Maven), Clojure (deps/lein), Rust, Ruby, PHP, .NET, and Elixir alongside the existing Go/Python/Node generators. Safe `build_subdir` resolution rejects path traversal (`..`).

## TDD Workflow

1. **Tests present** (from prior interrupted agent) — `test_dockerfile_templates.py` (15) and `test_ensure_dockerfile.py` (9) covering brief cases plus nested/override/path-traversal extras.
2. **Implementation reviewed against brief** — all Step 3 requirements already satisfied; no functional gaps found.
3. **Final run** — 47 passed (includes `test_language_detection.py` re-export regression).

## Changes

### `backend/app/core/git/dockerfile_templates.py` (new)

- `dockerfile_contents_for(info, *, override=None, from_git_clone=False) -> str`
- Templates: Go, Python, Node (+ git-clone variant), Java Gradle/Maven (temurin multi-stage; `./gradlew`/`./mvnw` with shell fallbacks; bootJar-then-build), Clojure tools-deps/lein, Rust, Ruby, PHP, Dotnet, Elixir
- `start_command` / `language_version` / `package_manager` honored via `BuildOverride` where relevant
- `UNKNOWN` → `DockerfileGenerationError`

### `backend/app/core/git/project_analysis.py` (modified)

- Re-exports `analyze_project` (Task 2) and `dockerfile_contents_for` (Task 3)
- `ensure_dockerfile_for_build(..., override: BuildOverride | None = None)`
- Effective root via safe `_effective_root` (`AnalysisError` on `..` escape)
- Writes Dockerfile under `build_subdir` when set; never overwrites existing file

### Tests

- `backend/tests/test_dockerfile_templates.py` — per-language keyword assertions
- `backend/tests/test_ensure_dockerfile.py` — resolution order, override force, nested write, path traversal

## Test Results

```
f:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests/test_ensure_dockerfile.py tests/test_dockerfile_templates.py tests/test_language_detection.py -q
47 passed, 1 warning in 0.13s
```

## Self-Review

| Check | Result |
|-------|--------|
| Never overwrite existing Dockerfile | ✓ |
| Unknown → `NeedsBuildOverrideError` | ✓ |
| Override forces language | ✓ |
| JVM / Clojure / Rust / Ruby / PHP / Dotnet / Elixir templates | ✓ |
| Safe `build_subdir` rejects `..` | ✓ |
| `analyze_project` re-export still identity-equal | ✓ (covered by language detection tests) |
| Only Task 3 files committed | ✓ (4 files) |

## Concerns

- Gradle spring-boot selection is a **runtime shell fallback** (`bootJar` then `build`), not a pre-write parse of the build file. Adequate for v1; a content heuristic could refine the generated RUN line later.
- Override `build_subdir` pointing at a missing directory fails at write time (`DockerfileGenerationError` via `OSError`) rather than a dedicated validation message.
- Error copy no longer enumerates marker filenames; it points users at manual language selection (modal path). Intentional for Task 3+.

---

## Fix round (reviewer: NEEDS_FIXES)

### Important 1 — Maven multi-jar COPY

Replaced `COPY --from=builder /src/target/*.jar ./app.jar` with a Gradle-style `find` into `/out/app.jar`, excluding `*-plain.jar`, then `COPY --from=builder /out/app.jar`. Test asserts no `target/*.jar` glob and presence of the plain-jar exclusion.

### Important 2 — Exhaustive match default arm

Added `case _:` raising `DockerfileGenerationError(language, "no built-in template for this language")` so future enum members cannot fall through and return `None`. Covered with a `model_construct` fake-language test.

### Important 3 — Honor override fields on remaining templates

Go, Python, Node (both variants), Rust, PHP, and Clojure now use `_language_version` / `_cmd_line` like Java/Ruby/Dotnet/Elixir. Tests cover version `FROM` tags and `CMD` for Go/Python/Node/Rust/PHP/Clojure.

### Important 4 — Hard-fail Clojure tools.deps / Elixir builds

Removed soft-fail `|| echo ...` paths. Clojure tools.deps requires a successful uberjar alias and `test -f /out/app.jar`. Elixir requires `mix release` and `test -d /src/_build/prod/rel`.

### Test output

```
f:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests/test_ensure_dockerfile.py tests/test_dockerfile_templates.py -q
27 passed, 1 warning in 0.12s
```

### Commit

`60192b8` — fix: harden Dockerfile templates for override and jar copy
