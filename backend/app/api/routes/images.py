"""Host image operations via orchestrator (stubs until wired)."""

from fastapi import APIRouter, HTTPException, status

router = APIRouter()


def _not_implemented() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet — no concrete orchestrator is wired.",
    )


@router.get("/")
async def list_images() -> None:
    """List available image tags on the host."""
    _not_implemented()


@router.post("/pull")
async def pull_image(image: str, tag: str = "latest") -> None:
    """Pull an image from a registry."""
    _not_implemented()


@router.post("/build")
async def build_image(
    path: str,
    tag: str,
    dockerfile: str = "Dockerfile",
) -> None:
    """Build an image from a build context directory."""
    _not_implemented()
