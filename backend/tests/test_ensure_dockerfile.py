"""Integration tests for ``ensure_dockerfile_for_build``'s resolution order."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.enums import BuildStrategy, SupportedLanguage
from app.core.exceptions import AnalysisError, NeedsBuildOverrideError
from app.core.git.project_analysis import ensure_dockerfile_for_build
from app.core.models import BuildOverride


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
    assert info.language is SupportedLanguage.JAVA
    body = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    assert "gradle" in body.lower() or "./gradlew" in body


def test_unknown_raises_needs_build_override(tmp_path: Path) -> None:
    with pytest.raises(NeedsBuildOverrideError):
        ensure_dockerfile_for_build(tmp_path)
    assert not (tmp_path / "Dockerfile").exists()


def test_override_forces_python(tmp_path: Path) -> None:
    strategy, info = ensure_dockerfile_for_build(
        tmp_path,
        override=BuildOverride(language=SupportedLanguage.PYTHON),
    )

    assert strategy is BuildStrategy.GENERATED_DOCKERFILE
    assert info.language is SupportedLanguage.PYTHON
    assert "python" in (tmp_path / "Dockerfile").read_text(encoding="utf-8").lower()


def test_override_wins_even_when_detection_succeeds(tmp_path: Path) -> None:
    """An explicit override always wins, even if markers would have inferred a language."""
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")

    strategy, info = ensure_dockerfile_for_build(
        tmp_path,
        override=BuildOverride(language=SupportedLanguage.RUBY),
    )

    assert strategy is BuildStrategy.GENERATED_DOCKERFILE
    assert info.language is SupportedLanguage.RUBY
    assert "bundle install" in (tmp_path / "Dockerfile").read_text(encoding="utf-8")


def test_nested_marker_writes_dockerfile_in_build_subdir(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "go.mod").write_text("module example\n", encoding="utf-8")

    strategy, info = ensure_dockerfile_for_build(tmp_path)

    assert strategy is BuildStrategy.GENERATED_DOCKERFILE
    assert info.build_subdir == "backend"
    assert info.dockerfile_path == "backend/Dockerfile"
    assert (backend_dir / "Dockerfile").is_file()
    assert not (tmp_path / "Dockerfile").is_file()


def test_override_build_subdir_relocates_effective_root(tmp_path: Path) -> None:
    service_dir = tmp_path / "service"
    service_dir.mkdir()

    strategy, info = ensure_dockerfile_for_build(
        tmp_path,
        override=BuildOverride(language=SupportedLanguage.GO, build_subdir="service"),
    )

    assert strategy is BuildStrategy.GENERATED_DOCKERFILE
    assert info.build_subdir == "service"
    assert (service_dir / "Dockerfile").is_file()


def test_override_build_subdir_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(AnalysisError):
        ensure_dockerfile_for_build(
            tmp_path,
            override=BuildOverride(language=SupportedLanguage.GO, build_subdir="../escape"),
        )


def test_dockerfile_exists_at_effective_root_is_not_overwritten(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "go.mod").write_text("module example\n", encoding="utf-8")
    (backend_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    strategy, info = ensure_dockerfile_for_build(tmp_path)

    assert strategy is BuildStrategy.DOCKERFILE_EXISTS
    assert (backend_dir / "Dockerfile").read_text(encoding="utf-8") == "FROM scratch\n"


def test_root_dockerfile_wins_over_nested_markers(tmp_path: Path) -> None:
    """Root Dockerfile takes precedence; nested markers must not force build_subdir."""
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "package.json").write_text("{}\n", encoding="utf-8")

    strategy, info = ensure_dockerfile_for_build(tmp_path)

    assert strategy is BuildStrategy.DOCKERFILE_EXISTS
    assert info.build_subdir is None
    assert info.dockerfile_path == "Dockerfile"
    assert (tmp_path / "Dockerfile").read_text(encoding="utf-8") == "FROM scratch\n"
    assert not (backend_dir / "Dockerfile").exists()


def test_explicit_override_build_subdir_ignores_root_dockerfile(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM root\n", encoding="utf-8")
    service_dir = tmp_path / "service"
    service_dir.mkdir()

    strategy, info = ensure_dockerfile_for_build(
        tmp_path,
        override=BuildOverride(language=SupportedLanguage.GO, build_subdir="service"),
    )

    assert strategy is BuildStrategy.GENERATED_DOCKERFILE
    assert info.build_subdir == "service"
    assert (service_dir / "Dockerfile").is_file()
    assert (tmp_path / "Dockerfile").read_text(encoding="utf-8") == "FROM root\n"
