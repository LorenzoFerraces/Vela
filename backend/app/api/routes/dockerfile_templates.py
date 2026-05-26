"""CRUD for per-user Dockerfile templates (PostgreSQL)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    DockerfileTemplateCreate,
    DockerfileTemplatePublic,
    DockerfileTemplateUpdate,
)
from app.core import user_library
from app.db.models import User

router = APIRouter()


@router.get("/", response_model=list[DockerfileTemplatePublic])
async def list_dockerfile_templates(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[DockerfileTemplatePublic]:
    """
    Retrieve Dockerfile templates owned by the authenticated caller.
    
    Returns:
        list[DockerfileTemplatePublic]: A list of DockerfileTemplatePublic instances representing templates owned by the caller.
    """
    rows = await user_library.list_dockerfile_templates(session, current_user.id)
    return [DockerfileTemplatePublic.model_validate(row) for row in rows]


@router.post(
    "/",
    response_model=DockerfileTemplatePublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_dockerfile_template(
    body: DockerfileTemplateCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DockerfileTemplatePublic:
    """
    Create a Dockerfile template owned by the current user.
    
    Parameters:
        body (DockerfileTemplateCreate): Template data (name and contents) to create.
    
    Returns:
        DockerfileTemplatePublic: The created template converted to the public schema.
    
    Raises:
        HTTPException: HTTP 400 Bad Request if creation fails due to invalid input or a naming conflict.
    """
    try:
        row = await user_library.create_dockerfile_template(
            session,
            current_user.id,
            name=body.name,
            contents=body.contents,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return DockerfileTemplatePublic.model_validate(row)


@router.get("/{template_id}", response_model=DockerfileTemplatePublic)
async def get_dockerfile_template(
    template_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DockerfileTemplatePublic:
    """
    Retrieve a Dockerfile template owned by the authenticated user.
    
    Parameters:
        template_id (uuid.UUID): UUID of the template to retrieve.
    
    Returns:
        DockerfileTemplatePublic: Public representation of the requested template.
    """
    row = await user_library.get_dockerfile_template(
        session, current_user.id, template_id
    )
    return DockerfileTemplatePublic.model_validate(row)


@router.patch("/{template_id}", response_model=DockerfileTemplatePublic)
async def update_dockerfile_template(
    template_id: uuid.UUID,
    body: DockerfileTemplateUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DockerfileTemplatePublic:
    """
    Update an existing Dockerfile template's name and/or contents.
    
    Parameters:
        template_id (uuid.UUID): Identifier of the template to update.
        body (DockerfileTemplateUpdate): Update payload; must include at least one of `name` or `contents`.
        
    Returns:
        DockerfileTemplatePublic: The updated Dockerfile template.
    
    Raises:
        HTTPException: 400 if neither `name` nor `contents` is provided, or if the update is invalid (validation error mapped from `ValueError`).
    """
    if body.name is None and body.contents is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one of name or contents.",
        )
    try:
        row = await user_library.update_dockerfile_template(
            session,
            current_user.id,
            template_id,
            name=body.name,
            contents=body.contents,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return DockerfileTemplatePublic.model_validate(row)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dockerfile_template(
    template_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """
    Delete the Dockerfile template identified by `template_id` that belongs to the authenticated user.
    
    Parameters:
        template_id (uuid.UUID): ID of the Dockerfile template to delete.
    """
    await user_library.delete_dockerfile_template(
        session, current_user.id, template_id
    )
