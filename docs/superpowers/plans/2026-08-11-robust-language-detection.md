# Robust Language Detection & Build Overrides — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect a broad set of languages (including JVM and Clojure), generate Dockerfiles when missing, and let users persist a manual `BuildOverride` via a shared modal on Containers and Stacks when inference fails.

**Architecture:** Split detection and Dockerfile templates out of `project_analysis.py`. Add `BuildOverride` + typed `NeedsBuildOverrideError`. Persist override on `stack_services` and `deployment_records`. Frontend shared modal opens on analyze hint or deploy error code `needs_build_override`.

**Tech Stack:** Python (FastAPI, SQLAlchemy, Pydantic, Pytest, Alembic), TypeScript/React, Playwright E2E

**Spec:** `docs/superpowers/specs/2026-08-11-robust-language-detection-design.md`

## Global Constraints

- Prefer existing Dockerfile at effective build root; never overwrite
- Detection: root first, then shallow scan depth ≤ 2 with ignore dirs from the spec
- Kotlin ships as `language=java` + optional `framework=kotlin` (no `KOTLIN` enum)
- New enum values: `php`, `dotnet`, `elixir`, `clojure`
- Python style: explicit types, `match`/`case` for language unions
- TypeScript: no `instanceof`; exhaustive `switch` with `never` default
- Tests: pytest from `backend/`; FakeContainerOrchestrator; no Docker required for unit/integration
- Alembic: next revision after `0015_stack_service_git_branch` → `0016_build_override`
- Exact package versions only if adding frontend deps (prefer no new deps)
- Do not commit unrelated WIP on `f/Stack`

---

## File map

| Path | Role |
|------|------|
| `backend/app/core/enums.py` | Extend `SupportedLanguage` |
| `backend/app/core/models.py` | `BuildOverride`; enrich `ProjectInfo` with `build_subdir` |
| `backend/app/core/exceptions.py` | `NeedsBuildOverrideError` |
| `backend/app/core/git/language_detection.py` | Marker scan + priority |
| `backend/app/core/git/dockerfile_templates.py` | Per-language Dockerfile text |
| `backend/app/core/git/project_analysis.py` | Orchestrate detect → generate → override |
| `backend/app/core/build/default_image_builder.py` | Pass override; honor `build_subdir` |
| `backend/app/db/models.py` | `build_override` on StackService + DeploymentRecord |
| `backend/alembic/versions/0016_build_override.py` | Migration |
| `backend/app/api/schemas.py` | Public schemas + analyze fields |
| `backend/app/api/errors.py` | Handler for `NeedsBuildOverrideError` |
| `backend/app/api/routes/builder.py` | Detect/analyze enrichment |
| `backend/app/api/routes/containers.py` | Accept + persist override |
| `backend/app/api/routes/stacks.py` | Accept + return override |
| `backend/app/core/stacks/deploy.py` | Pass service override into build |
| `frontend/src/api/client.ts` | Types + API |
| `frontend/src/pages/containers/BuildConfigModal.tsx` | Shared modal |
| `frontend/src/pages/ContainersPage.tsx` / run form hooks | Wire modal |
| `frontend/src/pages/stacks/*` | Wire modal + persist |
| `backend/tests/fixtures/projects/*` | Detection fixtures |
| `backend/tests/test_language_detection.py` | Unit tests |
| `backend/tests/test_dockerfile_templates.py` | Template tests |
| `frontend/e2e/build-override.spec.ts` | E2E unknown → modal → deploy |

---

### Task 1: Enum, `BuildOverride`, and `NeedsBuildOverrideError`

**Files:**
- Modify: `backend/app/core/enums.py`
- Modify: `backend/app/core/models.py`
- Modify: `backend/app/core/exceptions.py`
- Modify: `backend/app/core/__init__.py` (re-exports if used)
- Test: `backend/tests/test_build_override_model.py`

**Interfaces:**
- Produces: `SupportedLanguage` values `PHP`, `DOTNET`, `ELIXIR`, `CLOJURE`
- Produces: `class BuildOverride(BaseModel)` with fields `language`, `language_version`, `package_manager`, `build_subdir`, `start_command`
- Produces: `NeedsBuildOverrideError` with `code = "needs_build_override"` and `api_response_content()`
- Produces: `ProjectInfo.build_subdir: str | None = None`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_build_override_model.py
from app.core.enums import SupportedLanguage
from app.core.exceptions import NeedsBuildOverrideError
from app.core.models import BuildOverride


def test_supported_language_includes_new_values() -> None:
    assert SupportedLanguage.CLOJURE == "clojure"
    assert SupportedLanguage.PHP == "php"
    assert SupportedLanguage.DOTNET == "dotnet"
    assert SupportedLanguage.ELIXIR == "elixir"


def test_build_override_defaults() -> None:
    override = BuildOverride(language=SupportedLanguage.JAVA)
    assert override.language_version is None
    assert override.package_manager is None
    assert override.build_subdir is None
    assert override.start_command is None


def test_needs_build_override_error_payload() -> None:
    exc = NeedsBuildOverrideError("No Dockerfile and no recognized markers.")
    payload = exc.api_response_content()
    assert payload["code"] == "needs_build_override"
    assert "detail" in payload
```

- [ ] **Step 2: Run test — expect FAIL (missing enum members / types)**

Run: `cd backend && python -m pytest tests/test_build_override_model.py -q`

- [ ] **Step 3: Implement**

In `enums.py` add:

```python
PHP = "php"
DOTNET = "dotnet"
ELIXIR = "elixir"
CLOJURE = "clojure"
```

In `models.py` near `ProjectInfo`:

```python
class BuildOverride(BaseModel):
    language: SupportedLanguage
    language_version: str | None = None
    package_manager: str | None = None
    build_subdir: str | None = None
    start_command: list[str] | None = None
```

Add `build_subdir: str | None = None` to `ProjectInfo`.

In `exceptions.py`:

```python
class NeedsBuildOverrideError(BuilderError):
    """Detection failed; client should collect a BuildOverride via modal."""

    code = "needs_build_override"

    def __init__(self, message: str) -> None:
        super().__init__(message)

    def api_response_content(self) -> dict[str, object]:
        return {"code": self.code, "detail": str(self)}
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/enums.py backend/app/core/models.py backend/app/core/exceptions.py backend/tests/test_build_override_model.py
git commit -m "feat: add BuildOverride model and NeedsBuildOverrideError"
```

---

### Task 2: Language detection module + fixtures

**Files:**
- Create: `backend/app/core/git/language_detection.py`
- Create fixtures under `backend/tests/fixtures/projects/` (minimal marker files only)
- Create: `backend/tests/test_language_detection.py`
- Modify: `backend/app/core/git/project_analysis.py` to re-export `analyze_project` from detection (keep import path stable)

**Interfaces:**
- Consumes: `ProjectInfo`, `SupportedLanguage`, `AnalysisError`
- Produces: `def analyze_project(project_root: Path) -> ProjectInfo`
- Produces: `IGNORE_DIR_NAMES: frozenset[str]`
- Produces: `MAX_SCAN_DEPTH = 2`

**Fixture layout:**

```text
tests/fixtures/projects/
  go_root/go.mod
  python_req/requirements.txt
  node_pkg/package.json
  gradle_java/build.gradle
  maven_java/pom.xml
  clojure_deps/deps.edn
  clojure_lein/project.clj
  rust_cargo/Cargo.toml
  ruby_gem/Gemfile
  php_composer/composer.json
  elixir_mix/mix.exs
  dotnet_cs/App.csproj
  nested_node/backend/package.json
  nested_ignored/node_modules/package.json
  dockerfile_only/Dockerfile
```

- [ ] **Step 1: Write failing tests** covering root Gradle→java, deps.edn→clojure, nested `backend/package.json`, ignore `node_modules`, Dockerfile sets `has_dockerfile`, priority go.mod over package.json in same dir

```python
from pathlib import Path
from app.core.enums import SupportedLanguage
from app.core.git.language_detection import analyze_project

FIXTURES = Path(__file__).parent / "fixtures" / "projects"

def test_detect_gradle_as_java() -> None:
    info = analyze_project(FIXTURES / "gradle_java")
    assert info.language is SupportedLanguage.JAVA
    assert info.dependency_file == "build.gradle"

def test_detect_clojure_deps() -> None:
    info = analyze_project(FIXTURES / "clojure_deps")
    assert info.language is SupportedLanguage.CLOJURE

def test_shallow_nested_node() -> None:
    info = analyze_project(FIXTURES / "nested_node")
    assert info.language in (SupportedLanguage.JAVASCRIPT, SupportedLanguage.TYPESCRIPT)
    assert info.build_subdir == "backend"

def test_ignores_node_modules() -> None:
    info = analyze_project(FIXTURES / "nested_ignored")
    assert info.language is SupportedLanguage.UNKNOWN
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `language_detection.py`**

Implement:
- Collect candidates at root, else walk depth ≤2
- Skip ignore dirs from the spec
- Marker matchers per spec table
- Tie-break priority per spec
- Same-directory: `deps.edn` / `project.clj` beat Gradle/Maven
- Set `dependency_file` to relative path of winning marker; `build_subdir` to parent of marker relative to root (`None` if `.`)
- Dockerfile detection at effective roots

Keep `from app.core.git.project_analysis import analyze_project` working via re-export.

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: robust multi-language project detection with shallow scan"
```

---

### Task 3: Dockerfile templates + `ensure_dockerfile_for_build` with override

**Files:**
- Create: `backend/app/core/git/dockerfile_templates.py`
- Modify: `backend/app/core/git/project_analysis.py`
- Create: `backend/tests/test_dockerfile_templates.py`
- Create: `backend/tests/test_ensure_dockerfile.py`

**Interfaces:**
- Consumes: `ProjectInfo`, `BuildOverride`, `SupportedLanguage`
- Produces: `def dockerfile_contents_for(info: ProjectInfo, *, override: BuildOverride | None = None, from_git_clone: bool = False) -> str`
- Produces: `def ensure_dockerfile_for_build(project_root: Path, *, dockerfile_name: str = "Dockerfile", from_git_clone: bool = False, override: BuildOverride | None = None) -> tuple[BuildStrategy, ProjectInfo]`
- Raises: `NeedsBuildOverrideError` when unknown and no override; `DockerfileGenerationError` when language known but no template

- [ ] **Step 1: Failing tests**

```python
def test_existing_dockerfile_not_overwritten(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    strategy, info = ensure_dockerfile_for_build(tmp_path)
    assert strategy is BuildStrategy.DOCKERFILE_EXISTS
    assert (tmp_path / "Dockerfile").read_text(encoding="utf-8") == "FROM scratch\n"

def test_gradle_generates_dockerfile(tmp_path: Path) -> None:
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    (tmp_path / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    strategy, info = ensure_dockerfile_for_build(tmp_path)
    assert strategy is BuildStrategy.GENERATED_DOCKERFILE
    body = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    assert "gradle" in body.lower() or "./gradlew" in body

def test_unknown_raises_needs_build_override(tmp_path: Path) -> None:
    with pytest.raises(NeedsBuildOverrideError):
        ensure_dockerfile_for_build(tmp_path)

def test_override_forces_python(tmp_path: Path) -> None:
    ensure_dockerfile_for_build(
        tmp_path,
        override=BuildOverride(language=SupportedLanguage.PYTHON),
    )
    assert "python" in (tmp_path / "Dockerfile").read_text(encoding="utf-8").lower()
```

Also assert Clojure / Rust / Ruby / PHP / Dotnet / Elixir templates contain expected base image keywords.

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement templates**

Move existing Go/Python/Node generators into `dockerfile_templates.py`. Add:

- **Java Gradle:** eclipse-temurin build + JRE runtime; prefer `./gradlew`; spring-boot heuristic for `bootJar` when present in build file
- **Java Maven:** `./mvnw` or `mvn -DskipTests package`
- **Clojure deps / lein:** tools-deps or lein images; expose `start_command` as preferred for main class
- **Rust / Ruby / PHP / Dotnet / Elixir:** minimal templates per spec

`ensure_dockerfile_for_build` resolution:

1. Resolve effective root using safe `build_subdir` (reject `..`)
2. Dockerfile exists → `DOCKERFILE_EXISTS`
3. Override → generate from override language
4. Else analyze → UNKNOWN → `NeedsBuildOverrideError`
5. Else generate; missing template → `DockerfileGenerationError`

Update marker list in error messages.

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: Dockerfile templates for JVM, Clojure, and expanded languages"
```

---

### Task 4: Image builder + stack deploy pass override / build_subdir

**Files:**
- Modify: `backend/app/core/build/builder.py` (protocol signature if needed)
- Modify: `backend/app/core/build/default_image_builder.py`
- Modify: `backend/app/core/stacks/deploy.py`
- Update any Fake image builder used in tests
- Test: `backend/tests/test_default_image_builder_override.py`

**Interfaces:**
- Produces: `build_from_source(..., override: BuildOverride | None = None)`
- Build context path must be the effective subdirectory when `build_subdir` is set
- Stack deploy reads `service.build_override` JSON into `BuildOverride`

- [ ] **Step 1: Write failing test** that nested marker yields `build_image` called with `.../backend` path

- [ ] **Step 2: Implement wiring**

```python
strategy, info = ensure_dockerfile_for_build(
    Path(project_path),
    from_git_clone=source.git_url is not None,
    override=override,
)
build_root = Path(project_path)
if info.build_subdir:
    candidate = (build_root / info.build_subdir).resolve()
    if not candidate.is_relative_to(build_root.resolve()):
        raise AnalysisError(str(build_root), "invalid build_subdir")
    build_root = candidate
image_id = await self._orchestrator.build_image(
    str(build_root), tag=tag, dockerfile="Dockerfile"
)
```

In `deploy.py`, parse `service.build_override` → `BuildOverride` and pass through.

- [ ] **Step 3: Tests PASS + commit**

```bash
git commit -m "feat: honor build override and subdir in image builds"
```

---

### Task 5: DB migration for `build_override`

**Files:**
- Modify: `backend/app/db/models.py` — `StackService.build_override`, `DeploymentRecord.build_override`
- Create: `backend/alembic/versions/0016_build_override.py`

**Interfaces:**
- Produces: nullable JSON columns defaulting to `None`

- [ ] **Step 1: Add columns to models**

```python
build_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

on both `StackService` and `DeploymentRecord`.

- [ ] **Step 2: Alembic revision**

```python
revision = "0016_build_override"
down_revision = "0015_stack_service_git_branch"

def upgrade() -> None:
    op.add_column("stack_services", sa.Column("build_override", sa.JSON(), nullable=True))
    op.add_column("deployment_records", sa.Column("build_override", sa.JSON(), nullable=True))

def downgrade() -> None:
    op.drop_column("deployment_records", "build_override")
    op.drop_column("stack_services", "build_override")
```

- [ ] **Step 3: `alembic upgrade head` locally against dev DB**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: persist build_override on stacks and deployment records"
```

---

### Task 6: API schemas, error handler, analyze enrichment, route wiring

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/errors.py`
- Modify: `backend/app/api/routes/builder.py`
- Modify: `backend/app/api/routes/containers.py`
- Modify: `backend/app/api/routes/stacks.py`
- Modify: `backend/app/core/git/git_source_analysis.py`
- Modify: `backend/app/core/deploy/deployment_history.py`
- Test: `backend/tests/test_api_integration.py` (new cases)

**Interfaces:**
- `GitSourceAnalysis.needs_manual_build_config: bool = False`
- `GitSourceAnalysis.build_subdir: str | None = None`
- `RunFromSourceRequest.build_override` optional
- `StackServiceCreate` / `StackServicePublic` include `build_override`
- HTTP 422 with `{"code":"needs_build_override","detail":"..."}`

- [ ] **Step 1: Failing API test — stack create persists build_override**

```python
def test_stack_create_persists_build_override(api_client):
    body = {
        "name": "ovr",
        "services": [{
            "service_name": "app",
            "source_kind": "git",
            "source_ref": "https://github.com/example/app.git",
            "git_branch": "main",
            "build_override": {"language": "java", "package_manager": "gradle"},
        }],
    }
    resp = api_client.post("/api/stacks/", json=body)
    assert resp.status_code == 201
    assert resp.json()["services"][0]["build_override"]["language"] == "java"
```

- [ ] **Step 2: Implement schema fields + ORM mapping in stacks create/update/`_stack_to_public`**

- [ ] **Step 3: Exception handler for `NeedsBuildOverrideError`**

```python
@app.exception_handler(NeedsBuildOverrideError)
async def needs_build_override_handler(_request: Request, exc: NeedsBuildOverrideError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=exc.api_response_content(),
    )
```

Raise `NeedsBuildOverrideError` from `ensure_dockerfile_for_build` instead of generic `UnsupportedProjectError` for the unknown case.

- [ ] **Step 4: Containers run** passes `body.build_override` into `build_from_source` and stores on `DeploymentRecord`

- [ ] **Step 5: Tests PASS + commit**

```bash
git commit -m "feat: API support for build overrides and needs_build_override errors"
```

---

### Task 7: Frontend types + shared `BuildConfigModal`

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/containers/BuildConfigModal.tsx`
- Create: `frontend/src/pages/containers/buildOverride.ts`
- Modify: `frontend/src/index.css` (reuse compose-import modal patterns)

**Interfaces:**
- `BuildOverride` TS type matching backend
- `isNeedsBuildOverrideError(err: unknown): boolean` via `code` field on API error
- `<BuildConfigModal open onCancel onConfirm(override) initial? />`
- Language options: python, javascript, typescript, go, java, rust, ruby, php, dotnet, elixir, clojure
- Package manager select when language is java (gradle|maven), javascript/typescript (npm|pnpm|yarn), clojure (deps|lein)
- Optional version, subdir, start command

- [ ] **Step 1: Implement modal**
- [ ] **Step 2: `npm run build` (tsc) passes**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat: shared BuildConfigModal for manual language overrides"
```

---

### Task 8: Wire Containers run + analyze flow

**Files:**
- Modify: `frontend/src/pages/ContainersPage.tsx`
- Modify: `frontend/src/pages/containers/useGitSourceAnalysis.ts`
- Modify related run form state

**Behavior:**
- Keep `buildOverride` in run form state
- After analyze: if `needs_manual_build_config`, open modal; on confirm set override
- On run failure: if `code === 'needs_build_override'`, open modal; on confirm set override and optionally auto-retry run
- Include `build_override` in run payload

- [ ] **Step 1: Implement**
- [ ] **Step 2: Commit**

```bash
git commit -m "feat: containers flow prompts for build override when needed"
```

---

### Task 9: Wire Stacks builder + list deploy

**Files:**
- Modify: `frontend/src/pages/stacks/StackBuilderPage.tsx`
- Modify: `frontend/src/pages/stacks/ComposeImportReviewModal.tsx`
- Modify stacks list deploy handler
- Modify: `frontend/src/api/client.ts` stack types

**Behavior:**
- Git service can open BuildConfigModal and set `build_override`
- Persist via create/update stack
- List deploy: on `needs_build_override`, open modal for failing service (parse name from detail), PATCH override, redeploy

- [ ] **Step 1: Implement**
- [ ] **Step 2: Commit**

```bash
git commit -m "feat: stacks persist and prompt for per-service build overrides"
```

---

### Task 10: E2E coverage

**Files:**
- Create: `frontend/e2e/build-override.spec.ts`
- Extend `backend/app/e2e_support.py` if needed to stub analyze / accept override without flaky GitHub

**Scenario:**
1. Login as E2E user
2. Hit path that yields `needs_manual_build_config` or `needs_build_override`
3. Modal → select Java / Gradle → confirm
4. Assert override saved and deploy succeeds under fake orchestrator

- [ ] **Step 1: Write spec**
- [ ] **Step 2: `npm run test:e2e -- e2e/build-override.spec.ts` PASS**
- [ ] **Step 3: Commit**

```bash
git commit -m "test: e2e for build override modal on stacks/containers"
```

---

### Task 11: Deslop + short README note

**Files:**
- Touched implementation files
- `README.md` — one short bullet on supported languages + manual build override

- [ ] **Step 1: Deslop**
- [ ] **Step 2: Run focused pytest suite**
- [ ] **Step 3: Commit if README changed**

```bash
git commit -m "docs: note expanded language detection and build overrides"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Dockerfile never overwritten | 3 |
| Root then shallow depth ≤2 | 2 |
| JVM Gradle/Maven detection + templates | 2, 3 |
| Clojure detection + templates | 2, 3 |
| Rust/Ruby/PHP/.NET/Elixir | 2, 3 |
| Kotlin as java+framework | 2 |
| BuildOverride model + persistence | 1, 5, 6 |
| needs_build_override typed error | 1, 6 |
| Analyze needs_manual_build_config | 6, 8 |
| Modal on analyze + deploy fail | 7, 8, 9 |
| Containers + Stacks | 8, 9 |
| build_subdir honored in build | 4 |
| Tests + E2E | 2, 3, 6, 10 |

## Self-review notes

- No TBD placeholders in task steps
- Migration id `0016` assumes `0015_stack_service_git_branch` is on the branch
- Update Fake image builder signature in Task 4 alongside the real builder
- Keep stack deploy error detail including service name so the list-page modal can target the right service
