"""Image builder API (clone / local path → Dockerfile bootstrap → docker build)."""

from __future__ import annotations

from typing import Annotated

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_image_builder
from app.api.schemas import (
    AnalyzeGitSourceRequest,
    BuilderAnalyzeRequest,
    BuilderBuildRequest,
    GitSourceAnalysis,
)
from app.core.default_image_builder import DefaultImageBuilder, validate_local_build_context
from app.core.git_source_analysis import analyze_git_source
from app.core.models import BuildResult, ProjectInfo
from app.core.oauth import decrypt_identity_token, get_github_identity
from app.db.models import User

router = APIRouter()


@router.post("/build", response_model=BuildResult)
async def build_from_source(
    body: BuilderBuildRequest,
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
) -> BuildResult:
    """Full pipeline: clone or local path → ensure Dockerfile → ``docker build``."""
    return await image_builder.build_from_source(body.source, tag=body.tag)


@router.post("/analyze", response_model=ProjectInfo)
async def analyze(
    body: BuilderAnalyzeRequest,
    image_builder: Annotated[DefaultImageBuilder, Depends(get_image_builder)],
) -> ProjectInfo:
    """Inspect a local project directory (subject to ``VELA_ALLOWED_BUILD_ROOT`` when set)."""
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
    )


async def _github_token_for_analyze(
    session: AsyncSession,
    user: User,
    git_url: str,
) -> str | None:
    from app.api.routes.containers import _github_token_for_url

    return await _github_token_for_url(session, user, git_url)
