from pathlib import Path

import pytest

from app.core.enums import SupportedLanguage
from app.core.exceptions import AnalysisError
from app.core.git.language_detection import (
    IGNORE_DIR_NAMES,
    MAX_SCAN_DEPTH,
    analyze_project,
)

FIXTURES = Path(__file__).parent / "fixtures" / "projects"


def test_detect_go_at_root() -> None:
    info = analyze_project(FIXTURES / "go_root")
    assert info.language is SupportedLanguage.GO
    assert info.dependency_file == "go.mod"
    assert info.build_subdir is None


def test_detect_python_requirements() -> None:
    info = analyze_project(FIXTURES / "python_req")
    assert info.language is SupportedLanguage.PYTHON
    assert info.dependency_file == "requirements.txt"


def test_detect_node_package_json() -> None:
    info = analyze_project(FIXTURES / "node_pkg")
    assert info.language is SupportedLanguage.JAVASCRIPT
    assert info.dependency_file == "package.json"


def test_detect_gradle_as_java() -> None:
    info = analyze_project(FIXTURES / "gradle_java")
    assert info.language is SupportedLanguage.JAVA
    assert info.dependency_file == "build.gradle"


def test_detect_maven_as_java() -> None:
    info = analyze_project(FIXTURES / "maven_java")
    assert info.language is SupportedLanguage.JAVA
    assert info.dependency_file == "pom.xml"


def test_detect_clojure_deps() -> None:
    info = analyze_project(FIXTURES / "clojure_deps")
    assert info.language is SupportedLanguage.CLOJURE
    assert info.dependency_file == "deps.edn"


def test_detect_clojure_leiningen() -> None:
    info = analyze_project(FIXTURES / "clojure_lein")
    assert info.language is SupportedLanguage.CLOJURE
    assert info.dependency_file == "project.clj"


def test_detect_rust_cargo() -> None:
    info = analyze_project(FIXTURES / "rust_cargo")
    assert info.language is SupportedLanguage.RUST
    assert info.dependency_file == "Cargo.toml"


def test_detect_ruby_gemfile() -> None:
    info = analyze_project(FIXTURES / "ruby_gem")
    assert info.language is SupportedLanguage.RUBY
    assert info.dependency_file == "Gemfile"


def test_detect_php_composer() -> None:
    info = analyze_project(FIXTURES / "php_composer")
    assert info.language is SupportedLanguage.PHP
    assert info.dependency_file == "composer.json"


def test_detect_elixir_mix() -> None:
    info = analyze_project(FIXTURES / "elixir_mix")
    assert info.language is SupportedLanguage.ELIXIR
    assert info.dependency_file == "mix.exs"


def test_detect_dotnet_csproj() -> None:
    info = analyze_project(FIXTURES / "dotnet_cs")
    assert info.language is SupportedLanguage.DOTNET
    assert info.dependency_file == "App.csproj"


def test_shallow_nested_node() -> None:
    info = analyze_project(FIXTURES / "nested_node")
    assert info.language in (SupportedLanguage.JAVASCRIPT, SupportedLanguage.TYPESCRIPT)
    assert info.build_subdir == "backend"
    assert info.dependency_file == "backend/package.json"


def test_ignores_node_modules() -> None:
    info = analyze_project(FIXTURES / "nested_ignored")
    assert info.language is SupportedLanguage.UNKNOWN
    assert info.dependency_file is None


def test_dockerfile_only_sets_has_dockerfile() -> None:
    info = analyze_project(FIXTURES / "dockerfile_only")
    assert info.has_dockerfile is True
    assert info.dockerfile_path == "Dockerfile"
    assert info.language is SupportedLanguage.UNKNOWN


def test_priority_go_over_node_in_same_dir() -> None:
    info = analyze_project(FIXTURES / "priority_go_over_node")
    assert info.language is SupportedLanguage.GO
    assert info.dependency_file == "go.mod"


def test_priority_clojure_over_gradle_in_same_dir() -> None:
    info = analyze_project(FIXTURES / "jvm_clojure_priority")
    assert info.language is SupportedLanguage.CLOJURE
    assert info.dependency_file == "deps.edn"


def test_analyze_project_raises_for_missing_path(tmp_path: Path) -> None:
    with pytest.raises(AnalysisError):
        analyze_project(tmp_path / "does-not-exist")


def test_ignore_dir_names_cover_common_noise_dirs() -> None:
    for name in ("node_modules", "vendor", "target", ".git", "__pycache__"):
        assert name in IGNORE_DIR_NAMES


def test_max_scan_depth_is_two() -> None:
    assert MAX_SCAN_DEPTH == 2


def test_project_analysis_reexports_analyze_project() -> None:
    from app.core.git.project_analysis import analyze_project as reexported

    assert reexported is analyze_project
