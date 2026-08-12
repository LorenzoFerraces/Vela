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

- [ ] **Step 1: Write failing tests** covering root Gradleâ†’java, deps.ednâ†’clojure, nested `backend/package.json`, ignore `node_modules`, Dockerfile sets `has_dockerfile`, priority go.mod over package.json in same dir

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

- [ ] **Step 2: Run â€” expect FAIL**

- [ ] **Step 3: Implement `language_detection.py`**

Implement:
- Collect candidates at root, else walk depth â‰¤2
- Skip ignore dirs from the spec
- Marker matchers per spec table
- Tie-break priority per spec
- Same-directory: `deps.edn` / `project.clj` beat Gradle/Maven
- Set `dependency_file` to relative path of winning marker; `build_subdir` to parent of marker relative to root (`None` if `.`)
- Dockerfile detection at effective roots

Keep `from app.core.git.project_analysis import analyze_project` working via re-export.

- [ ] **Step 4: Run tests â€” PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: robust multi-language project detection with shallow scan"
```

---
