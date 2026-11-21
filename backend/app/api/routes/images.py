"""Host image operations via orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_orchestrator, require_admin
from app.core.audit.service import emit_audit_log
from app.core.build.default_image_builder import validate_local_build_context
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.git.project_analysis import ensure_dockerfile_for_build
from app.db.models import User


class ImageBuildRequest(BaseModel):
    """Build an image from an existing directory on the server (no Git clone)."""

    context_path: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description=(
            "Absolute path to a build context on the server; a Dockerfile is generated "
            "when missing but project markers are detected (same rules as /api/builder/build)."
        ),
    )
    tag: str = Field(..., min_length=1, max_length=256)
    dockerfile: str = Field(default="Dockerfile", max_length=256)


router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/")
async def list_images(
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
) -> dict[str, list[str]]:
    """List image tags known to the local Docker engine."""
    tags = await orchestrator.list_images()
    return {"images": tags}


@router.post("/pull")
async def pull_image(
    image: str,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
    tag: str = "latest",
) -> dict[str, str]:
    """Pull an image from a registry (admin only)."""
    await orchestrator.pull_image(image, tag=tag)
    ref = f"{image}:{tag}" if ":" not in image else image
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="image.pull",
        target_type="image",
        target_id=ref,
    )
    await session.commit()
    return {"detail": "ok", "ref": ref}


@router.post("/build")
async def build_image(
    body: ImageBuildRequest,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> dict[str, str]:
    """Build from a server-local directory (admin only)."""
    ctx = validate_local_build_context(Path(body.context_path))
    ensure_dockerfile_for_build(ctx, dockerfile_name=body.dockerfile)
    image_id = await orchestrator.build_image(str(ctx), tag=body.tag, dockerfile=body.dockerfile)
    await emit_audit_log(
        session,
        user_id=current_user.id,
        action="image.build",
        target_type="image",
        target_id=body.tag,
        details={"image_id": image_id},
    )
    await session.commit()
    return {"image_id": image_id, "tag": body.tag}
