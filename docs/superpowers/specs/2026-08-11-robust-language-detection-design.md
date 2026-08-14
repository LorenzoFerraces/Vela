# Robust Language Detection & Build Overrides

**Date:** 2026-08-11  
**Status:** Approved

## Problem

Vela’s git deploy path only recognizes Go, Python, and Node markers at the **repo root**. JVM projects (e.g. Gradle Spring/Java apps) fail with a generic “no Dockerfile / no supported markers” error even when `build.gradle` is present. `SupportedLanguage` already lists Java, Rust, and Ruby, but they are neither detected nor given Dockerfile templates. Users also have no way to manually specify language/version when inference fails.

## Goals

1. Prefer an existing root `Dockerfile`; never overwrite it.
2. Otherwise auto-detect language robustly (root first, then shallow scan) and **generate** a Dockerfile when a template exists.
3. Broaden the language matrix (JVM, Rust, Ruby, PHP, .NET, Elixir, **Clojure**, plus existing Go/Python/Node).
4. When detection fails (or language has no template), open a **shared modal** so the user can choose language, version, and related build fields; persist that as a **build override** on Containers and Stacks.
5. Surface a typed API error (`needs_build_override`) so deploy can reopen the modal instead of a dead-end banner.

## Non-goals

- Cloud Native Buildpacks / Paketo as the primary build path.
- Overwriting or “improving” user-authored Dockerfiles.
- Deep monorepo orchestration (multi-service inference inside one git URL).
- AI inventing Dockerfiles when markers are absent (modal + override instead).

## Approach

Split today’s monolithic `project_analysis.py` into:

| Module | Responsibility |
|--------|----------------|
| `language_detection.py` | Marker scan (root + depth ≤2), ignore dirs, priority, `ProjectInfo` |
| `dockerfile_templates.py` | Per-language Dockerfile generators |
| `project_analysis.py` | `ensure_dockerfile_for_build` orchestration + override merge |

Shared **`BuildOverride`** schema used by Containers run requests, Stack services, analyze/detect responses, and the UI modal.

## Detection

### Scan order

1. If `{project_root}/Dockerfile` exists → `has_dockerfile=true`; still record language from markers when useful for UI hints.
2. Collect markers at root.
3. If no language inferred, shallow walk **depth ≤ 2**, skipping: `.git`, `node_modules`, `vendor`, `target`, `build`, `dist`, `.gradle`, `.idea`, `__pycache__`, `.venv`, `venv`, `vendor/bundle`, `obj`, `_build`, `.dart_tool`.
4. Prefer the **shallowest** matching path; on ties use the documented marker priority list.

### Marker → language (v1)

| Language | Markers (examples) |
|----------|-------------------|
| Go | `go.mod` |
| Python | `requirements.txt`, `pyproject.toml`, `Pipfile` |
| JavaScript / TypeScript | `package.json` (+ `tsconfig.json` / typescript dep → TS) |
| Java | `pom.xml`, `build.gradle`, `build.gradle.kts`, `settings.gradle`, `settings.gradle.kts` |
| Kotlin | Detect via Gradle/Maven + Kotlin indicators (`src/main/kotlin`, kotlin plugin); **v1 reports `language=java`** with optional `framework=kotlin` — same JVM Dockerfile family. No separate `SupportedLanguage.KOTLIN` in v1. |
| Clojure | `deps.edn`, `project.clj`, `bb.edn` (Babashka → Clojure family; generate with Clojure tools or note Babashka image if only `bb.edn`) |
| Rust | `Cargo.toml` |
| Ruby | `Gemfile` |
| PHP | `composer.json` |
| Dotnet | `*.csproj`, `*.fsproj`, `*.vbproj` |
| Elixir | `mix.exs` |

Extend `SupportedLanguage` with: `php`, `dotnet`, `elixir`, `clojure`. Do not add `kotlin` in v1.

### Priority (tie-break, strongest first)

Dockerfile presence (for build strategy) is independent. For language:

1. `go.mod`
2. JVM / Clojure manifests (`pom.xml`, Gradle files, `deps.edn`, `project.clj`)
3. `Cargo.toml`
4. `mix.exs`
5. `*.csproj` / `*.fsproj` / `*.vbproj`
6. `composer.json`
7. `Gemfile`
8. `package.json`
9. Python manifests (`pyproject.toml`, `requirements.txt`, `Pipfile`)

When both Gradle and `deps.edn` exist at the same depth, prefer the more specific app marker if one path is nested; at the same directory prefer **Clojure** if `deps.edn`/`project.clj` present alongside a parent Gradle wrapper used only as tooling — document edge cases in tests; default: Clojure markers beat generic Gradle in the same directory.

### Nested apps

If the winning marker lives under a subdirectory, set `ProjectInfo` / override `build_subdir` to that relative path. Dockerfile generation and `docker build` context should use that subdirectory (or copy from repo root with `WORKDIR` set appropriately — prefer **build context = subdir** when the manifest is self-contained).

## Dockerfile generation

Rules:

- Never write a Dockerfile if one already exists at the effective build root.
- Use wrappers when present (`./gradlew`, `./mvnw`, `lein` via image, Clojure CLI tools image).
- Multi-stage builds for compiled languages (JVM, Go, Rust, .NET).
- Sensible default `EXPOSE` ports (e.g. 8080 JVM/Clojure, 3000 Node, 8000 Python).

### Template coverage (v1)

| Language | Generate? | Notes |
|----------|-----------|--------|
| Go / Python / Node / TS | Yes | Keep / lightly improve existing |
| Java (Gradle) | Yes | Multi-stage; `./gradlew bootJar` or `installDist` / `jar` fallbacks documented in template comments |
| Java (Maven) | Yes | `./mvnw` or `mvn package` |
| Clojure | Yes | `deps.edn`: Clojure tools + `clojure -T:build` / uberjar patterns with conservative CMD; `project.clj`: Leiningen image + `lein uberjar` |
| Rust | Yes | `cargo build --release` |
| Ruby | Yes | Bundler + `rackup`/`puma`/`rails` heuristic or generic `bundle exec` + override `start_command` |
| PHP | Yes | Composer + `php -S` or apache/php image baseline |
| .NET | Yes | `dotnet publish` multi-stage |
| Elixir | Yes | `mix release` when possible; else clear error + modal |

Languages detected but not templated yet: raise a clear error naming the language and set `needs_build_override` / invite Dockerfile.

## Build override

```text
BuildOverride:
  language: SupportedLanguage          # required
  language_version: str | null         # e.g. "21", "1.27", "20"
  package_manager: str | null          # gradle | maven | npm | pnpm | yarn | pip | bundler | lein | deps | ...
  build_subdir: str | null
  start_command: list[str] | null
```

**Resolution order in `ensure_dockerfile_for_build`:**

1. Existing Dockerfile at effective root → `DOCKERFILE_EXISTS`
2. Else if `override` set → generate from override language (markers may still inform package_manager defaults)
3. Else auto-detect → generate if template exists
4. Else raise typed `NeedsBuildOverrideError` (`code: needs_build_override`)

## API

- Enrich git analyze / add `POST /api/builder/detect-project` (or extend analyze-source) with:
  - `language`, `language_version`, `dependency_file`, `build_subdir`, `has_dockerfile`
  - `needs_manual_build_config: bool`
  - `supported_override_fields` / language options for the modal
- `RunFromSourceRequest.build_override` optional
- `StackServiceCreate` / public: `build_override` optional
- Persist:
  - `stack_services.build_override` JSON nullable (Alembic)
  - `deployment_records.build_override` JSON nullable (Alembic)
- Map `NeedsBuildOverrideError` → HTTP 422 (or 400) with stable `code` + `detail` for the UI

## UI (Containers + Stacks)

Shared **Build config modal**:

- **Triggers:** analyze returns `needs_manual_build_config`; deploy/build returns `needs_build_override`.
- **Fields:** language, version (defaults per language), package manager when relevant, optional subdirectory, optional start command.
- **Confirm:** write override into run-form state or stack service; retry analyze or deploy.
- **Stacks list deploy:** on per-service failure with that code, open modal for that service → PATCH stack → redeploy.

Git branch remains a text field (unchanged). Override is independent of branch.

## Testing

- Fixture trees under `backend/tests/fixtures/projects/` for each language + nested `backend/` app + ignore-dir noise.
- Unit: detection priority, shallow scan, Dockerfile never overwritten, override wins, JVM Gradle/Maven, Clojure `deps.edn` / `project.clj`.
- Integration: analyze `needs_manual_build_config`; stack CRUD persists override; container run stores override on deployment record.
- Frontend: modal open/save; Containers + Stacks paths; E2E with fake orchestrator for unknown → override → success.

## Rollout

1. Migrations for `build_override` columns.
2. Backend detection + templates + error code.
3. Shared modal + wire Containers then Stacks.
4. No change required for repos that already have a Dockerfile.
5. Gradle-at-root apps (e.g. Commit-y-me-voy) deploy without the modal once Java templates land.

## Open implementation notes

- Exact Gradle task (`bootJar` vs `jar`) may use light file heuristics (`spring-boot` plugin in build file) with a safe fallback and override `start_command`.
- Clojure uberjar main class may require `start_command` override when not inferable — modal should expose it for Clojure by default.
