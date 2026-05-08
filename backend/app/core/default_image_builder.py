"""Concrete :class:`~app.core.builder.ImageBuilder` using Git clone + Dockerfile bootstrap."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.core.builder import ImageBuilder
from app.core.exceptions import AnalysisError
from app.core.git_ops import git_shallow_clone, rm_tree
from app.core.models import BuildResult, ProjectInfo, ProjectSource
from app.core.orchestrator import ContainerOrchestrator
from app.core.project_analysis import (
    analyze_project,
    dockerfile_contents_for,
    ensure_dockerfile_for_build,
)


def validate_local_build_context(path: Path) -> Path:
    """Resolve ``path`` and optionally enforce :envvar:`VELA_ALLOWED_BUILD_ROOT`."""
    p = path.expanduser().resolve(strict=False)
    if not p.is_dir():
        raise AnalysisError(str(path), "local_path must be an existing directory")
    allowed = os.environ.get("VELA_ALLOWED_BUILD_ROOT", "").strip()
    if allowed:
        base = Path(allowed).resolve()
        try:
            p.relative_to(base)
        except ValueError as exc:
            raise AnalysisError(
                str(path),
                f"local_path must be inside VELA_ALLOWED_BUILD_ROOT ({base})",
            ) from exc
    return p


class DefaultImageBuilder(ImageBuilder):
    """Clone or use a local directory, ensure a Dockerfile, then ``docker build``."""

    def __init__(self, orchestrator: ContainerOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def clone_repository(
        self,
        git_url: str,
        *,
        branch: str = "main",
        access_token: str | None = None,
    ) -> str:
        """Clone into a fresh temp directory; return path to the repo root.

        The parent of the returned path is a temp prefix ``vela-clone-*``;
        callers that use this alone should delete that parent when finished.
        """
        root = Path(tempfile.mkdtemp(prefix="vela-clone-"))
        dest = root / "repo"
        await git_shallow_clone(
            url=git_url.strip(),
            branch=branch,
            dest=dest,
            access_token=access_token,
        )
        return str(dest.resolve())

    async def analyze(self, project_path: str) -> ProjectInfo:
        return analyze_project(Path(project_path))

    async def generate_dockerfile(
        self, project_path: str, project_info: ProjectInfo
    ) -> str:
        _ = project_path  # reserved for future per-path templates
        return dockerfile_contents_for(project_info)

    async def build_from_source(
        self,
        source: ProjectSource,
        *,
        tag: str,
        access_token: str | None = None,
    ) -> BuildResult:
        tmp_parent: Path | None = None
        project_path: str
        if source.git_url:
            project_path = await self.clone_repository(
                source.git_url,
                branch=source.branch,
                access_token=access_token,
            )
            tmp_parent = Path(project_path).parent
        elif source.local_path:
            resolved = validate_local_build_context(Path(source.local_path))
            project_path = str(resolved)
        else:
            raise AnalysisError("", "ProjectSource requires git_url or local_path")

        try:
            strategy, info = ensure_dockerfile_for_build(
                Path(project_path), from_git_clone=source.git_url is not None
            )
            image_id = await self._orchestrator.build_image(
                project_path, tag=tag, dockerfile="Dockerfile"
            )
            return BuildResult(
                image_id=image_id,
                image_tag=tag,
                strategy=strategy,
                build_log="",
                project_info=info,
            )
        finally:
            if tmp_parent is not None:
                rm_tree(tmp_parent)
