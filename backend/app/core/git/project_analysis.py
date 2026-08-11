"""Orchestrate Dockerfile generation for projects analyzed by ``language_detection``.

``analyze_project`` and ``dockerfile_contents_for`` are re-exported here (rather than
redefined) so existing callers can keep importing them from this module while the
marker-scanning and template logic live in ``language_detection`` / ``dockerfile_templates``.
"""

from __future__ import annotations

from pathlib import Path

from app.core.enums import BuildStrategy, SupportedLanguage
from app.core.exceptions import AnalysisError, DockerfileGenerationError, NeedsBuildOverrideError
from app.core.git.dockerfile_templates import dockerfile_contents_for
from app.core.git.language_detection import analyze_project
from app.core.models import BuildOverride, ProjectInfo

__all__ = [
    "analyze_project",
    "dockerfile_contents_for",
    "ensure_dockerfile_for_build",
]


def _resolve_build_subdir(override: BuildOverride | None, info: ProjectInfo) -> str | None:
    if override is not None and override.build_subdir:
        return override.build_subdir
    return info.build_subdir


def _effective_root(root: Path, build_subdir: str | None) -> Path:
    if not build_subdir:
        return root
    candidate = (root / build_subdir).resolve()
    if not candidate.is_relative_to(root):
        raise AnalysisError(str(root), f"invalid build_subdir: {build_subdir!r}")
    return candidate


def ensure_dockerfile_for_build(
    project_root: Path,
    *,
    dockerfile_name: str = "Dockerfile",
    from_git_clone: bool = False,
    override: BuildOverride | None = None,
) -> tuple[BuildStrategy, ProjectInfo]:
    """Resolve a build strategy for ``project_root``.

    Resolution order: an existing Dockerfile at the effective root always wins (never
    overwritten); otherwise an explicit ``override`` generates a Dockerfile for its
    language; otherwise auto-detection generates one when the detected language is known;
    otherwise a typed ``NeedsBuildOverrideError`` asks the caller to collect an override.
    """
    root = project_root.resolve()
    info = analyze_project(root)

    build_subdir = _resolve_build_subdir(override, info)
    effective_root = _effective_root(root, build_subdir)
    target = effective_root / dockerfile_name
    dockerfile_path = target.relative_to(root).as_posix()

    if target.is_file():
        return BuildStrategy.DOCKERFILE_EXISTS, info.model_copy(
            update={
                "has_dockerfile": True,
                "dockerfile_path": dockerfile_path,
                "build_subdir": build_subdir,
            }
        )

    if override is not None:
        language = override.language
    elif info.language is not SupportedLanguage.UNKNOWN:
        language = info.language
    else:
        raise NeedsBuildOverrideError(
            "No Dockerfile in project root and no supported markers were found. "
            "Add a Dockerfile, or select a language and build settings manually."
        )

    result_info = info.model_copy(update={"language": language, "build_subdir": build_subdir})
    body = dockerfile_contents_for(result_info, override=override, from_git_clone=from_git_clone)

    try:
        target.write_text(body, encoding="utf-8")
    except OSError as exc:
        raise DockerfileGenerationError(
            str(language), f"failed to write {target}: {exc}"
        ) from exc

    return BuildStrategy.GENERATED_DOCKERFILE, result_info.model_copy(
        update={"has_dockerfile": True, "dockerfile_path": dockerfile_path}
    )
