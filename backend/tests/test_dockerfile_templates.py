"""Unit tests for per-language Dockerfile generation (no filesystem I/O)."""

from __future__ import annotations

import pytest

from app.core.enums import SupportedLanguage
from app.core.exceptions import DockerfileGenerationError
from app.core.git.dockerfile_templates import dockerfile_contents_for
from app.core.models import BuildOverride, ProjectInfo


def _info(language: SupportedLanguage, **overrides: object) -> ProjectInfo:
    return ProjectInfo(language=language, **overrides)


def test_go_template_unchanged_keywords() -> None:
    body = dockerfile_contents_for(_info(SupportedLanguage.GO))
    assert "golang" in body.lower()
    assert "go build" in body


def test_python_template_unchanged_keywords() -> None:
    body = dockerfile_contents_for(_info(SupportedLanguage.PYTHON))
    assert "python" in body.lower()


def test_node_template_default_vs_git_clone() -> None:
    default_body = dockerfile_contents_for(_info(SupportedLanguage.JAVASCRIPT))
    git_body = dockerfile_contents_for(
        _info(SupportedLanguage.JAVASCRIPT), from_git_clone=True
    )
    assert "npm run dev || npm run preview" in default_body
    assert "npm ci" in git_body
    assert default_body != git_body


def test_java_gradle_template_by_default() -> None:
    body = dockerfile_contents_for(_info(SupportedLanguage.JAVA))
    assert "gradle" in body.lower()


def test_java_maven_template_from_dependency_file() -> None:
    info = _info(SupportedLanguage.JAVA, dependency_file="pom.xml")
    body = dockerfile_contents_for(info)
    assert "mvn" in body.lower() or "mvnw" in body.lower()
    assert "maven" in body.lower()


def test_java_package_manager_override_wins_over_dependency_file() -> None:
    info = _info(SupportedLanguage.JAVA, dependency_file="pom.xml")
    override = BuildOverride(language=SupportedLanguage.JAVA, package_manager="gradle")
    body = dockerfile_contents_for(info, override=override)
    assert "gradle" in body.lower()


def test_java_start_command_override_sets_cmd() -> None:
    info = _info(SupportedLanguage.JAVA)
    override = BuildOverride(
        language=SupportedLanguage.JAVA,
        start_command=["java", "-jar", "custom.jar"],
    )
    body = dockerfile_contents_for(info, override=override)
    assert '["java", "-jar", "custom.jar"]' in body


def test_clojure_deps_template_by_default() -> None:
    body = dockerfile_contents_for(_info(SupportedLanguage.CLOJURE))
    assert "clojure" in body.lower()
    assert "tools-deps" in body.lower() or "clojure -t" in body.lower()


def test_clojure_lein_template_from_dependency_file() -> None:
    info = _info(SupportedLanguage.CLOJURE, dependency_file="project.clj")
    body = dockerfile_contents_for(info)
    assert "lein" in body.lower()


def test_rust_template_keywords() -> None:
    body = dockerfile_contents_for(_info(SupportedLanguage.RUST))
    assert "cargo build --release" in body


def test_ruby_template_keywords() -> None:
    body = dockerfile_contents_for(_info(SupportedLanguage.RUBY))
    assert "bundle install" in body


def test_php_template_keywords() -> None:
    body = dockerfile_contents_for(_info(SupportedLanguage.PHP))
    assert "composer install" in body


def test_dotnet_template_keywords() -> None:
    body = dockerfile_contents_for(_info(SupportedLanguage.DOTNET))
    assert "dotnet publish" in body.lower()


def test_elixir_template_keywords() -> None:
    body = dockerfile_contents_for(_info(SupportedLanguage.ELIXIR))
    assert "mix release" in body.lower()


def test_unknown_language_raises_dockerfile_generation_error() -> None:
    with pytest.raises(DockerfileGenerationError):
        dockerfile_contents_for(_info(SupportedLanguage.UNKNOWN))
