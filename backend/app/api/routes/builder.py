"""Image builder API (clone / local path → Dockerfile bootstrap → docker build)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_image_builder, require_admin
from app.api.schemas import (
    AnalyzeGitSourceRequest,
    BuilderAnalyzeRequest,
    BuilderBuildRequest,
    GitSourceAnalysis,
)
from app.core.audit.service import emit_audit_log
from app.core.build.default_image_builder import (
    DefaultImageBuilder,
    validate_local_build_context,
)
from app.core.git.git_source_analysis import analyze_git_source
from app.core.models import BuildResult, ProjectInfo
from app.db.models import User

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/build", response_model=BuildResult)
async def build_from_source(
    body: BuilderBuildRequest,
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> BuildResult:
    """Full pipeline: clone or local path → ensure Dockerfile → docker build (admin only)."""
    result = await image_builder.build_from_source(
        body.source,
        tag=body.tag,
        override=body.build_override,
    )
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="builder.build",
        target_type="build",
        target_id=result.image_tag,
    )
    await session.commit()
    return result


@router.post("/analyze", response_model=ProjectInfo)
async def analyze(
    body: BuilderAnalyzeRequest,
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
    current_user: Annotated[User, Depends(require_admin)],
) -> ProjectInfo:
    """Inspect a local project directory (admin only)."""
    ctx = validate_local_build_context(Path(body.project_path))
    return await image_builder.analyze(str(ctx))


@router.post("/analyze-source", response_model=GitSourceAnalysis)
async def analyze_git_source_route(
    body: AnalyzeGitSourceRequest,
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GitSourceAnalysis:
    """Analyze a Git repository for deploy form pre-fill (Gemini when configured)."""
    git_url = body.git_url.strip()
    access_token = await _github_token_for_analyze(session, current_user, git_url)
    return await analyze_git_source(
        image_builder,
        git_url=git_url,
        git_branch=body.git_branch.strip() or "main",
        access_token=access_token,
        session=session,
        user_id=current_user.id,
        use_server_default=body.use_server_default,
    )


async def _github_token_for_analyze(
    session: AsyncSession,
    user: User,
    git_url: str,
) -> str | None:
    from app.core.deploy.github_auth import github_token_for_url

    return await github_token_for_url(session, user, git_url)
