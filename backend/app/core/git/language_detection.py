"""Detect a project's language from filesystem markers (root first, then a shallow scan)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

from app.core.enums import SupportedLanguage
from app.core.exceptions import AnalysisError
from app.core.models import ProjectInfo

MAX_SCAN_DEPTH = 2

IGNORE_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "vendor",
        "target",
        "build",
        "dist",
        ".gradle",
        ".idea",
        "__pycache__",
        ".venv",
        "venv",
        "bundle",
        "obj",
        "_build",
        ".dart_tool",
    }
)

_MarkerMatcher = Callable[[Path], str | None]


def _match_exact(*names: str) -> _MarkerMatcher:
    def _matcher(directory: Path) -> str | None:
        for name in names:
            if (directory / name).is_file():
                return name
        return None

    return _matcher


def _match_glob(*patterns: str) -> _MarkerMatcher:
    def _matcher(directory: Path) -> str | None:
        for pattern in patterns:
            matches = sorted(directory.glob(pattern))
            if matches:
                return matches[0].name
        return None

    return _matcher


# Ascending priority; second int breaks same-directory ties (e.g. Clojure over Gradle).
_MARKER_RULES: list[tuple[tuple[int, int], SupportedLanguage, _MarkerMatcher]] = [
    ((1, 0), SupportedLanguage.GO, _match_exact("go.mod")),
    ((2, 0), SupportedLanguage.CLOJURE, _match_exact("deps.edn", "project.clj", "bb.edn")),
    (
        (2, 1),
        SupportedLanguage.JAVA,
        _match_exact(
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "settings.gradle",
            "settings.gradle.kts",
        ),
    ),
    ((3, 0), SupportedLanguage.RUST, _match_exact("Cargo.toml")),
    ((4, 0), SupportedLanguage.ELIXIR, _match_exact("mix.exs")),
    ((5, 0), SupportedLanguage.DOTNET, _match_glob("*.csproj", "*.fsproj", "*.vbproj")),
    ((6, 0), SupportedLanguage.PHP, _match_exact("composer.json")),
    ((7, 0), SupportedLanguage.RUBY, _match_exact("Gemfile")),
    ((8, 0), SupportedLanguage.JAVASCRIPT, _match_exact("package.json")),
    (
        (9, 0),
        SupportedLanguage.PYTHON,
        _match_exact("requirements.txt", "pyproject.toml", "Pipfile"),
    ),
]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _detect_kotlin_framework(directory: Path, marker_filename: str) -> str | None:
    if (directory / "src" / "main" / "kotlin").is_dir():
        return "kotlin"
    if not marker_filename.startswith("build.gradle"):
        return None
    content = _read_text(directory / marker_filename)
    if content is not None and "kotlin" in content.lower():
        return "kotlin"
    return None


def _read_json(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _resolve_js_language(directory: Path) -> SupportedLanguage:
    if (directory / "tsconfig.json").is_file():
        return SupportedLanguage.TYPESCRIPT
    data = _read_json(directory / "package.json") or {}
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    if "typescript" in deps:
        return SupportedLanguage.TYPESCRIPT
    return SupportedLanguage.JAVASCRIPT


def _directory_marker(
    directory: Path,
) -> tuple[tuple[int, int], SupportedLanguage, str] | None:
    for rank, language, matcher in _MARKER_RULES:
        filename = matcher(directory)
        if filename is not None:
            return rank, language, filename
    return None


def _child_dirs(directory: Path) -> Iterator[Path]:
    try:
        children = sorted(directory.iterdir())
    except OSError:
        return
    for child in children:
        if child.is_dir() and child.name not in IGNORE_DIR_NAMES:
            yield child


def _dirs_at_depth(root: Path, depth: int) -> Iterator[Path]:
    if depth == 0:
        yield root
        return
    for parent in _dirs_at_depth(root, depth - 1):
        yield from _child_dirs(parent)


def _find_marker_dir(
    root: Path,
) -> tuple[Path, SupportedLanguage, str] | None:
    for depth in range(MAX_SCAN_DEPTH + 1):
        candidates: list[tuple[tuple[int, int], Path, SupportedLanguage, str]] = []
        for directory in _dirs_at_depth(root, depth):
            found = _directory_marker(directory)
            if found is not None:
                rank, language, filename = found
                candidates.append((rank, directory, language, filename))
        if candidates:
            candidates.sort(key=lambda candidate: (candidate[0][0], candidate[1].as_posix()))
            _, directory, language, filename = candidates[0]
            return directory, language, filename
    return None


def _detect_dockerfile(root: Path, effective_root: Path) -> tuple[bool, str | None]:
    for candidate_dir in (effective_root, root):
        dockerfile = candidate_dir / "Dockerfile"
        if dockerfile.is_file():
            return True, dockerfile.relative_to(root).as_posix()
    return False, None


def analyze_project(project_root: Path) -> ProjectInfo:
    """Inspect a project directory: root markers first, then a shallow, ignore-aware scan."""
    root = project_root.resolve()
    if not root.is_dir():
        raise AnalysisError(str(project_root), "path is not a directory")

    marker = _find_marker_dir(root)

    if marker is None:
        language = SupportedLanguage.UNKNOWN
        dependency_file = None
        build_subdir = None
        framework = None
        effective_root = root
    else:
        marker_dir, language, filename = marker
        if language is SupportedLanguage.JAVASCRIPT:
            language = _resolve_js_language(marker_dir)
        framework = (
            _detect_kotlin_framework(marker_dir, filename)
            if language is SupportedLanguage.JAVA
            else None
        )
        relative_dir = marker_dir.relative_to(root)
        build_subdir = None if relative_dir == Path() else relative_dir.as_posix()
        dependency_file = (
            filename if build_subdir is None else f"{build_subdir}/{filename}"
        )
        effective_root = marker_dir

    has_dockerfile, dockerfile_path = _detect_dockerfile(root, effective_root)

    return ProjectInfo(
        language=language,
        framework=framework,
        dependency_file=dependency_file,
        has_dockerfile=has_dockerfile,
        dockerfile_path=dockerfile_path,
        build_subdir=build_subdir,
    )
