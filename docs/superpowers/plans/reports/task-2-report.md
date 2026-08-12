# Task 2 Report: Language detection module + fixtures

## Status: Done

## Summary

Added `backend/app/core/git/language_detection.py` implementing `analyze_project` per the
design doc's Detection section:

- **Scan order**: root markers first; if none found, breadth-first shallow walk depth ≤
  `MAX_SCAN_DEPTH` (2), skipping `IGNORE_DIR_NAMES` (`.git`, `node_modules`, `vendor`, `target`,
  `build`, `dist`, `.gradle`, `.idea`, `__pycache__`, `.venv`, `venv`, `bundle`, `obj`, `_build`,
  `.dart_tool`). The shallowest matching directory wins; ties broken by marker priority, then by
  relative path for determinism.
- **Markers**: go.mod; deps.edn/project.clj/bb.edn (Clojure); pom.xml/build.gradle(.kts)/
  settings.gradle(.kts) (Java); Cargo.toml; mix.exs; *.csproj/*.fsproj/*.vbproj; composer.json;
  Gemfile; package.json (+ tsconfig.json/`typescript` dep → TypeScript); requirements.txt/
  pyproject.toml/Pipfile.
- **Priority**: encoded as `(tier, subtier)` tuples matching the spec's 9-tier list; within the
  JVM/Clojure tier, Clojure markers beat Gradle/Maven when co-located in the same directory.
- **Nested apps**: `build_subdir` set to the winning marker's parent dir (relative, POSIX
  separators, `None` at root); `dependency_file` is the marker's path relative to root.
- **Dockerfile**: checked at the effective root (winning marker's dir) first, then project root;
  sets `has_dockerfile` / `dockerfile_path` independent of language detection.

`project_analysis.py` now re-exports `analyze_project` from `language_detection` (verified via
`is` identity in a test) instead of defining its own copy; `dockerfile_contents_for` and
`ensure_dockerfile_for_build` are otherwise unchanged and still import `analyze_project`
successfully.

## Fixtures

Added 16 minimal marker-only fixture trees under `backend/tests/fixtures/projects/`: one per
language (go_root, python_req, node_pkg, gradle_java, maven_java, clojure_deps, clojure_lein,
rust_cargo, ruby_gem, php_composer, elixir_mix, dotnet_cs), plus `nested_node/backend/` (shallow
scan + build_subdir), `nested_ignored/node_modules/` (ignore-dir proof), `dockerfile_only/`
(Dockerfile-only, no markers), `priority_go_over_node/` (go.mod + package.json same dir), and
`jvm_clojure_priority/` (deps.edn + build.gradle same dir, Clojure must win).

Note: opening `gradle_java`/`jvm_clojure_priority` in an IDE with Java/Gradle tooling installed
auto-generated a `.gradle/` cache dir under each; these were deleted and excluded from the commit
(fixtures ended up with only the intended marker file per directory).

## Tests

`backend/tests/test_language_detection.py` — 21 tests, all passing: one detection test per
language, nested shallow-scan + `build_subdir`, ignore-dir behavior, Dockerfile-only detection,
both priority tie-break cases, `AnalysisError` on a missing path, `IGNORE_DIR_NAMES` /
`MAX_SCAN_DEPTH` constant checks, and the `project_analysis` re-export identity check.

Full backend suite: `209 passed, 1 failed` — the failure
(`test_finds_hostname_style_service_names` in `test_service_link_detection.py`) is pre-existing,
unrelated StackBuilder WIP already present in the working tree before this task; untouched by
this change.

## Concerns

- `dockerfile_contents_for` in `project_analysis.py` still lacks match arms for
  `PHP`/`DOTNET`/`ELIXIR` (raises via the `UNKNOWN` branch's `DockerfileGenerationError` only for
  `JAVA`/`RUST`/`RUBY`, so those three new languages would hit a non-exhaustive `match` and raise
  `TypeError` at runtime). Out of scope for Task 2 (templates land in a later task per the design
  doc), but flagging since `SupportedLanguage` now includes them.
- Priority tie-break for same-depth *different-directory* candidates falls back to sorting by
  relative path (undocumented in the spec); only exercised implicitly, not by a dedicated test.

## Commit

`a60e1f6` — "feat: robust multi-language project detection with shallow scan" (21 files: module,
fixtures, tests only — no StackBuilder/compose files staged).

---

## Fix round (reviewer: NEEDS_FIXES)

### Critical — gitignored fixture

`nested_ignored/node_modules/package.json` matched the root `.gitignore`'s `node_modules/` rule,
so it was never actually tracked and `test_ignores_node_modules` would fail on a fresh clone/CI
checkout. Fixed by moving the fixture to `nested_ignored/vendor/package.json` — `vendor` is in
`IGNORE_DIR_NAMES` and is **not** matched by any root `.gitignore` rule (checked directly:
`.gitignore` only ignores `node_modules/`, `.venv/`, `venv/`, `build/`, `dist/`, `__pycache__/`,
not `vendor/`, `target/`, `obj/`, `bundle/`, `_build/`, `.dart_tool/`). Verified with
`git add -n` (staged cleanly) and `git ls-files backend/tests/fixtures/projects/nested_ignored`
(returns the tracked `vendor/package.json` path). Renamed the test to
`test_ignores_vendor_dir` and updated its docstring to explain why `vendor` was chosen over
`node_modules`.

### Important — Clojure ranked above Java globally, not just same-directory

`_find_marker_dir`'s cross-directory candidate sort used the full `(tier, subtier)` tuple
(Clojure `(2, 0)`, Java `(2, 1)`), so Clojure would beat Java even when the two markers lived in
**different** directories at the same scan depth — contradicting the spec, which only prefers
Clojure over Gradle/Maven when they're co-located in the same directory. Fixed by sorting
cross-directory candidates on the primary tier only (`candidate[0][0]`), with the path-based
fallback applying to any same-tier tie (Clojure vs. Java included). The same-directory rule is
untouched: `_directory_marker` still resolves a single winner per directory by iterating
`_MARKER_RULES` in order, so Clojure still wins over a co-located Gradle file. Added
`cross_dir_tie/` fixture (`alpha_java/build.gradle` + `beta_clojure/deps.edn`, same depth,
different dirs) and a new test asserting the alphabetically-first `alpha_java` (Java) wins, not
Clojure.

### Should-fix — Kotlin framework hint

Added (small, as suggested): when the winning marker resolves to `JAVA`, check for
`src/main/kotlin/` under the marker directory, or a case-insensitive `"kotlin"` substring in the
Gradle build file content, and set `ProjectInfo.framework = "kotlin"` if either matches (v1 still
reports `language=java` per the spec — no separate `SupportedLanguage.KOTLIN`). Added
`gradle_kotlin/build.gradle` fixture (Kotlin Gradle plugin id) and a test asserting
`language is JAVA` with `framework == "kotlin"`.

### Verification

```
F:\lolo\fac\Vela\.venv\Scripts\python.exe -m pytest tests/test_language_detection.py -q
....................... [100%]
23 passed, 1 warning in 0.18s
```

```
git ls-files backend/tests/fixtures/projects/nested_ignored
backend/tests/fixtures/projects/nested_ignored/vendor/package.json
```

Full backend suite: `210 passed, 1 failed` — same pre-existing, unrelated
`test_service_link_detection.py::test_finds_hostname_style_service_names` failure as before
(StackBuilder WIP, untouched by this change); +2 passing tests vs. the prior run (23 vs. 21 in
`test_language_detection.py`, one net removed via rename plus two new).

### Fix commit

`fdc1bca` — "fix: make nested ignore fixture trackable; same-dir Clojure priority only" (6 files:
`language_detection.py`, `test_language_detection.py`, and 3 new fixture trees — no
StackBuilder/compose files staged).
