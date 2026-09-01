"""Unit tests for per-language Dockerfile generation (no filesystem I/O)."""

from __future__ import annotations

import json

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
    assert "COPY --from=builder /out/app.jar" in body
    assert "target/*.jar" not in body
    assert '*-plain.jar' in body


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
    assert "|| echo" not in body
    assert "test -f /out/app.jar" in body


def test_clojure_lein_template_from_dependency_file() -> None:
    info = _info(SupportedLanguage.CLOJURE, dependency_file="project.clj")
    body = dockerfile_contents_for(info)
    assert "lein" in body.lower()


def test_clojure_honors_language_version_and_start_command() -> None:
    override = BuildOverride(
        language=SupportedLanguage.CLOJURE,
        language_version="17",
        start_command=["java", "-cp", "app.jar", "clojure.main", "-m", "myapp.core"],
    )
    body = dockerfile_contents_for(_info(SupportedLanguage.CLOJURE), override=override)
    assert "temurin-17" in body
    assert '["java", "-cp", "app.jar", "clojure.main", "-m", "myapp.core"]' in body


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
    assert "|| echo" not in body
    assert "test -d /src/_build/prod/rel" in body


def test_go_python_node_rust_php_honor_override_fields() -> None:
    cases: list[tuple[SupportedLanguage, str, list[str], str]] = [
        (SupportedLanguage.GO, "1.22", ["./custom"], "golang:1.22-alpine"),
        (SupportedLanguage.PYTHON, "3.11", ["uvicorn", "app:app"], "python:3.11-slim"),
        (SupportedLanguage.JAVASCRIPT, "22", ["npm", "start"], "node:22-bookworm-slim"),
        (SupportedLanguage.RUST, "1.80", ["./bin/app"], "rust:1.80-slim"),
        (SupportedLanguage.PHP, "8.2", ["php", "public/index.php"], "php:8.2-cli"),
    ]
    for language, version, start_command, from_fragment in cases:
        override = BuildOverride(
            language=language,
            language_version=version,
            start_command=start_command,
        )
        body = dockerfile_contents_for(_info(language), override=override)
        assert from_fragment in body
        assert "CMD " + json.dumps(start_command) in body


def test_unknown_language_raises_dockerfile_generation_error() -> None:
    with pytest.raises(DockerfileGenerationError) as exc_info:
        dockerfile_contents_for(_info(SupportedLanguage.UNKNOWN))
    assert "cannot generate a Dockerfile without a known language" in str(exc_info.value)


def test_match_default_arm_message_for_unhandled_language() -> None:
    """New enum members must hit the default arm, not fall through to None."""

    class FakeLanguage:
        def __str__(self) -> str:
            return "cobol"

    info = ProjectInfo.model_construct(language=FakeLanguage())  # type: ignore[arg-type]
    with pytest.raises(DockerfileGenerationError) as exc_info:
        dockerfile_contents_for(info)
    assert "no built-in template for this language" in str(exc_info.value)
