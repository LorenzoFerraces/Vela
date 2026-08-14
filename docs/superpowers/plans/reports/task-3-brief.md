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

- [ ] **Step 2: Run â€” FAIL**

- [ ] **Step 3: Implement templates**

Move existing Go/Python/Node generators into `dockerfile_templates.py`. Add:

- **Java Gradle:** eclipse-temurin build + JRE runtime; prefer `./gradlew`; spring-boot heuristic for `bootJar` when present in build file
- **Java Maven:** `./mvnw` or `mvn -DskipTests package`
- **Clojure deps / lein:** tools-deps or lein images; expose `start_command` as preferred for main class
- **Rust / Ruby / PHP / Dotnet / Elixir:** minimal templates per spec

`ensure_dockerfile_for_build` resolution:

1. Resolve effective root using safe `build_subdir` (reject `..`)
2. Dockerfile exists â†’ `DOCKERFILE_EXISTS`
3. Override â†’ generate from override language
4. Else analyze â†’ UNKNOWN â†’ `NeedsBuildOverrideError`
5. Else generate; missing template â†’ `DockerfileGenerationError`

Update marker list in error messages.

- [ ] **Step 4: Run tests â€” PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: Dockerfile templates for JVM, Clojure, and expanded languages"
```

---
