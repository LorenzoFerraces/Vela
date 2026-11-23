"""Write-only secrets API: metadata is visible, values never are."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import SecretCreate, SecretPublic, SecretValueUpdate
from app.core.exceptions import ProjectAccessDeniedError
from app.core.projects.enums import can_write
from app.core.projects.repository import list_project_ids_for_user, require_membership
from app.core.secret_store import create_secret, set_secret_value
from app.db.models import Secret, SecretVersion, User

router = APIRouter(dependencies=[Depends(get_current_user)])


def _require_single_scope(
    owner_user_id: uuid.UUID | None, project_id: uuid.UUID | None
) -> None:
    if (owner_user_id is None) == (project_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A secret must have exactly one scope: an owner or a project.",
        )


async def _latest_versions(session: AsyncSession) -> dict[uuid.UUID, int]:
    rows = (
        await session.execute(
            select(SecretVersion.secret_id, func.max(SecretVersion.version)).group_by(
                SecretVersion.secret_id
            )
        )
    ).all()
    return {secret_id: version for secret_id, version in rows}


def _secret_to_public(
    secret: Secret, latest_versions: dict[uuid.UUID, int]
) -> SecretPublic:
    _require_single_scope(secret.owner_user_id, secret.project_id)
    version = latest_versions.get(secret.id)
    return SecretPublic(
        id=secret.id,
        name=secret.name,
        project_id=secret.project_id,
        has_value=version is not None,
        latest_version=version or 0,
        created_at=secret.created_at,
    )


async def _require_write_access(
    session: AsyncSession, secret: Secret, user: User
) -> None:
    _require_single_scope(secret.owner_user_id, secret.project_id)
    if secret.project_id is not None:
        membership = await require_membership(
            session, project_id=secret.project_id, user_id=user.id
        )
        if not can_write(membership.role):
            raise ProjectAccessDeniedError(
                "You do not have permission to modify secrets in this project."
            )
    elif secret.owner_user_id != user.id:
        raise ProjectAccessDeniedError(
            "You do not have permission to modify this secret."
        )


async def _load_visible_secret(
    session: AsyncSession, secret_id: uuid.UUID, user: User
) -> Secret | None:
    project_ids = await list_project_ids_for_user(session, user.id)
    return (
        await session.execute(
            select(Secret).where(
                Secret.id == secret_id,
                or_(
                    Secret.owner_user_id == user.id,
                    Secret.project_id.in_(project_ids),
                ),
            )
        )
    ).scalar_one_or_none()


@router.get("/", response_model=list[SecretPublic])
async def list_secrets(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[SecretPublic]:
    project_ids = await list_project_ids_for_user(session, current_user.id)
    secrets = (
        await session.execute(
            select(Secret)
            .where(
                or_(
                    Secret.owner_user_id == current_user.id,
                    Secret.project_id.in_(project_ids),
                )
            )
            .order_by(Secret.name)
        )
    ).scalars().all()
    latest_versions = await _latest_versions(session)
    return [_secret_to_public(secret, latest_versions) for secret in secrets]


@router.post("/", response_model=SecretPublic, status_code=status.HTTP_201_CREATED)
async def create_project_secret(
    body: SecretCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SecretPublic:
    owner_user_id = None if body.project_id is not None else current_user.id
    _require_single_scope(owner_user_id, body.project_id)
    if body.project_id is not None:
        membership = await require_membership(
            session, project_id=body.project_id, user_id=current_user.id
        )
        if not can_write(membership.role):
            raise ProjectAccessDeniedError(
                "You do not have permission to create secrets in this project."
            )
    query = select(Secret).where(Secret.name == body.name)
    if body.project_id is not None:
        query = query.where(Secret.project_id == body.project_id)
    else:
        query = query.where(Secret.owner_user_id == owner_user_id)
    if (await session.execute(query)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A secret named {body.name!r} already exists in this scope.",
        )
    secret = await create_secret(
        session,
        owner_user_id=owner_user_id,
        project_id=body.project_id,
        name=body.name,
        value=body.value,
    )
    latest_versions = await _latest_versions(session)
    return _secret_to_public(secret, latest_versions)


@router.patch("/{secret_id}", response_model=SecretPublic)
async def rotate_secret_value(
    secret_id: uuid.UUID,
    body: SecretValueUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SecretPublic:
    secret = await _load_visible_secret(session, secret_id, current_user)
    if secret is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Secret not found.")
    await _require_write_access(session, secret, current_user)
    await set_secret_value(session, secret, body.value)
    latest_versions = await _latest_versions(session)
    return _secret_to_public(secret, latest_versions)


@router.delete("/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    secret_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    secret = await _load_visible_secret(session, secret_id, current_user)
    if secret is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Secret not found.")
    await _require_write_access(session, secret, current_user)
    await session.execute(
        delete(SecretVersion).where(SecretVersion.secret_id == secret.id)
    )
    await session.delete(secret)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
