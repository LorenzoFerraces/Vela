"""Project and team membership API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    IncomingProjectInvitationPublic,
    MyProjectRolePublic,
    ProjectCreate,
    ProjectInvitationCreate,
    ProjectInvitationPublic,
    ProjectMemberPublic,
    ProjectMemberUpdate,
    ProjectPublic,
)
from app.core.projects import (
    ProjectRole,
    accept_invitation,
    cancel_invitation,
    create_invitation,
    create_shared_project,
    leave_project,
    list_incoming_invitations_for_user,
    list_members,
    list_pending_invitations_for_project,
    list_projects_for_user,
    reject_invitation,
    remove_member,
    require_membership,
    require_owner,
    require_project,
    update_member_role,
    owner_email_for_project,
)
from app.db.models import User

router = APIRouter()


def _project_public(
    *,
    project_id: uuid.UUID,
    name: str,
    is_personal: bool,
    role: str,
    owner_email: str,
) -> ProjectPublic:
    return ProjectPublic(
        id=project_id,
        name=name,
        is_personal=is_personal,
        role=role,
        owner_email=owner_email,
    )


@router.get("/", response_model=list[ProjectPublic])
async def list_user_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectPublic]:
    rows = await list_projects_for_user(session, current_user.id)
    return [
        _project_public(
            project_id=row.project.id,
            name=row.project.name,
            is_personal=row.project.is_personal,
            role=row.role.value,
            owner_email=row.owner_email,
        )
        for row in rows
    ]


@router.post("/", response_model=ProjectPublic, status_code=status.HTTP_201_CREATED)
async def create_user_project(
    body: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectPublic:
    row = await create_shared_project(
        session,
        user_id=current_user.id,
        name=body.name,
    )
    return _project_public(
        project_id=row.project.id,
        name=row.project.name,
        is_personal=row.project.is_personal,
        role=row.role.value,
        owner_email=row.owner_email,
    )


@router.get("/invitations/incoming", response_model=list[IncomingProjectInvitationPublic])
async def list_incoming_invitations(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[IncomingProjectInvitationPublic]:
    rows = await list_incoming_invitations_for_user(session, current_user.id)
    return [
        IncomingProjectInvitationPublic(
            id=row.invitation_id,
            project_id=row.project_id,
            project_name=row.project_name,
            inviter_email=row.inviter_email,
            role=row.role.value,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post(
    "/invitations/{invitation_id}/accept",
    response_model=ProjectPublic,
    status_code=status.HTTP_200_OK,
)
async def accept_project_invitation(
    invitation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectPublic:
    row = await accept_invitation(
        session, invitation_id=invitation_id, user_id=current_user.id
    )
    return _project_public(
        project_id=row.project.id,
        name=row.project.name,
        is_personal=row.project.is_personal,
        role=row.role.value,
        owner_email=row.owner_email,
    )


@router.post("/invitations/{invitation_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_project_invitation(
    invitation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await reject_invitation(
        session, invitation_id=invitation_id, user_id=current_user.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}", response_model=ProjectPublic)
async def get_project(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectPublic:
    membership = await require_membership(
        session, project_id=project_id, user_id=current_user.id
    )
    project = await require_project(session, project_id)
    owner_email = await owner_email_for_project(session, project_id)
    return _project_public(
        project_id=project.id,
        name=project.name,
        is_personal=project.is_personal,
        role=ProjectRole(membership.role).value,
        owner_email=owner_email,
    )


@router.get("/{project_id}/members", response_model=list[ProjectMemberPublic])
async def list_project_members(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectMemberPublic]:
    await require_membership(
        session, project_id=project_id, user_id=current_user.id
    )
    rows = await list_members(session, project_id)
    return [
        ProjectMemberPublic(
            user_id=row.user_id,
            email=row.email,
            role=row.role.value,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/{project_id}/members/me", response_model=MyProjectRolePublic)
async def get_my_project_role(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MyProjectRolePublic:
    membership = await require_membership(
        session, project_id=project_id, user_id=current_user.id
    )
    return MyProjectRolePublic(
        project_id=project_id,
        role=ProjectRole(membership.role).value,
    )


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMemberPublic,
)
async def patch_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: ProjectMemberUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectMemberPublic:
    row = await update_member_role(
        session,
        project_id=project_id,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        role=ProjectRole(body.role),
    )
    return ProjectMemberPublic(
        user_id=row.user_id,
        email=row.email,
        role=row.role.value,
        created_at=row.created_at,
    )


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await remove_member(
        session,
        project_id=project_id,
        actor_user_id=current_user.id,
        target_user_id=user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_user_project(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await leave_project(
        session,
        project_id=project_id,
        user_id=current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/invitations", response_model=list[ProjectInvitationPublic])
async def list_project_invitations(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectInvitationPublic]:
    await require_owner(session, project_id=project_id, user_id=current_user.id)
    rows = await list_pending_invitations_for_project(session, project_id)
    return [
        ProjectInvitationPublic(
            id=row.invitation_id,
            invitee_user_id=row.invitee_user_id,
            email=row.email,
            role=row.role.value,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post(
    "/{project_id}/invitations",
    response_model=ProjectInvitationPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_invitation(
    project_id: uuid.UUID,
    body: ProjectInvitationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectInvitationPublic:
    row = await create_invitation(
        session,
        project_id=project_id,
        actor_user_id=current_user.id,
        invitee_email=body.email,
        role=ProjectRole(body.role),
    )
    return ProjectInvitationPublic(
        id=row.invitation_id,
        invitee_user_id=row.invitee_user_id,
        email=row.email,
        role=row.role.value,
        created_at=row.created_at,
    )


@router.delete(
    "/{project_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_invitation(
    project_id: uuid.UUID,
    invitation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await cancel_invitation(
        session,
        project_id=project_id,
        invitation_id=invitation_id,
        actor_user_id=current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
