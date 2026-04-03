"""Image builder API (stubs until a concrete builder exists)."""

from fastapi import APIRouter, HTTPException, status

from app.core.models import ProjectSource

router = APIRouter()


def _not_implemented() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet — no concrete image builder is wired.",
    )


@router.post("/build")
async def build_from_source(
    source: ProjectSource,
    tag: str,
) -> None:
    """Full pipeline: clone → analyse → generate/detect Dockerfile → build."""
    _not_implemented()


@router.post("/analyze")
async def analyze(project_path: str) -> None:
    """Inspect a local project directory and detect its characteristics."""
    _not_implemented()
