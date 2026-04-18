"""Image builder API (clone / local path → Dockerfile bootstrap → docker build)."""

from __future__ import annotations

from typing import Annotated

from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.deps import get_image_builder
from app.api.schemas import BuilderAnalyzeRequest, BuilderBuildRequest
from app.core.default_image_builder import DefaultImageBuilder, validate_local_build_context
from app.core.models import BuildResult, ProjectInfo

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
