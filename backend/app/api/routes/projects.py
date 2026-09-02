"""Project and team membership API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_orchestrator
from app.api.schemas import (
    IncomingProjectInvitationPublic,
    MyProjectRolePublic,
    ProjectCreate,
    ProjectInvitationCreate,
    ProjectInvitationPublic,
    ProjectMemberPublic,
    ProjectMemberUpdate,
    ProjectPublic,
    ProjectStorageQuotaPublic,
    ProjectStorageQuotaUpdate,
)
from app.core.containers.orchestrator import ContainerOrchestrator
from app.core.exceptions import ProjectAccessDeniedError, TeamStorageQuotaError
from app.core.projects import (
    ProjectRole,
    accept_invitation,
    cancel_invitation,
    create_invitation,
    create_shared_project,
    get_membership,
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
from app.core.quotas import (
    TeamStorageQuotaSummary,
    environment_quota_bytes,
    format_gib,
    team_storage_quota_summary,
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
    storage_quota_bytes: int | None,
) -> ProjectPublic:
    return ProjectPublic(
        id=project_id,
        name=name,
        is_personal=is_personal,
        role=role,
        owner_email=owner_email,
        storage_quota_bytes=storage_quota_bytes,
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
            storage_quota_bytes=row.project.storage_quota_bytes,
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
        storage_quota_bytes=row.project.storage_quota_bytes,
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
        storage_quota_bytes=row.project.storage_quota_bytes,
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
        storage_quota_bytes=project.storage_quota_bytes,
    )


def _storage_quota_public(
    summary: TeamStorageQuotaSummary,
) -> ProjectStorageQuotaPublic:
    return ProjectStorageQuotaPublic(
        quota_bytes=summary.quota_bytes,
        used_bytes=summary.used_bytes,
        container_disk_bytes=summary.container_disk_bytes,
        uploads_bytes=summary.uploads_bytes,
        over_quota=summary.over_quota,
        source=summary.source,
    )


@router.get("/{project_id}/storage-quota", response_model=ProjectStorageQuotaPublic)
async def get_project_storage_quota(
    project_id: uuid.UUID,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectStorageQuotaPublic:
    membership = await get_membership(
        session, project_id=project_id, user_id=current_user.id
    )
    if membership is None:
        raise ProjectAccessDeniedError(
            "You must be a member of this team to view its storage quota."
        )
    project = await require_project(session, project_id)
    summary = await team_storage_quota_summary(session, orchestrator, project)
    return _storage_quota_public(summary)


@router.patch(
    "/{project_id}/storage-quota", response_model=ProjectStorageQuotaPublic
)
async def update_project_storage_quota(
    project_id: uuid.UUID,
    body: ProjectStorageQuotaUpdate,
    orchestrator: Annotated[ContainerOrchestrator, Depends(get_orchestrator)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectStorageQuotaPublic:
    membership = await require_membership(
        session, project_id=project_id, user_id=current_user.id
    )
    if ProjectRole(membership.role) != ProjectRole.OWNER:
        raise ProjectAccessDeniedError(
            "Only the team owner can change the storage quota."
        )
    project = await require_project(session, project_id)
    requested = body.storage_quota_bytes
    if requested is not None:
        platform_quota = environment_quota_bytes()
        if platform_quota is not None and requested > platform_quota:
            raise TeamStorageQuotaError(
                "Team quota cannot exceed the platform limit "
                f"of {format_gib(platform_quota)}."
            )
    project.storage_quota_bytes = requested
    await session.commit()
    await session.refresh(project)
    summary = await team_storage_quota_summary(session, orchestrator, project)
    return _storage_quota_public(summary)


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
