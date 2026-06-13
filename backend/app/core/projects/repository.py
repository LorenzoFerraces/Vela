"""Project and invitation persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.exceptions import (
    AlreadyProjectMemberError,
    DuplicateInvitationError,
    InvitationAlreadyRespondedError,
    InvitationNotFoundError,
    ProjectAccessDeniedError,
    ProjectMemberNotFoundError,
    ProjectNotFoundError,
    UserNotRegisteredError,
)
from app.core.projects.bootstrap import ensure_personal_workspace
from app.core.projects.enums import InvitationStatus, ProjectRole, is_owner
from app.db.models import Organization, Project, ProjectInvitation, ProjectMembership, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ProjectWithRole:
    project: Project
    role: ProjectRole
    owner_email: str


@dataclass(frozen=True)
class MemberRow:
    user_id: uuid.UUID
    email: str
    role: ProjectRole
    created_at: datetime


@dataclass(frozen=True)
class OutgoingInvitationRow:
    invitation_id: uuid.UUID
    invitee_user_id: uuid.UUID
    email: str
    role: ProjectRole
    created_at: datetime


@dataclass(frozen=True)
class IncomingInvitationRow:
    invitation_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    inviter_email: str
    role: ProjectRole
    created_at: datetime


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
    return await session.get(Project, project_id)


async def require_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await get_project(session, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    return project


async def get_membership(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ProjectMembership | None:
    return await session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
    )


async def require_membership(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ProjectMembership:
    membership = await get_membership(session, project_id=project_id, user_id=user_id)
    if membership is None:
        raise ProjectMemberNotFoundError(str(project_id), str(user_id))
    return membership


async def require_owner(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ProjectMembership:
    membership = await require_membership(
        session, project_id=project_id, user_id=user_id
    )
    if not is_owner(membership.role):
        raise ProjectAccessDeniedError("Only the project owner can perform this action.")
    return membership


async def list_projects_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[ProjectWithRole]:
    owner_membership = aliased(ProjectMembership)
    owner_user = aliased(User)
    result = await session.execute(
        select(Project, ProjectMembership.role, owner_user.email)
        .join(ProjectMembership, ProjectMembership.project_id == Project.id)
        .join(
            owner_membership,
            (owner_membership.project_id == Project.id)
            & (owner_membership.role == ProjectRole.OWNER),
        )
        .join(owner_user, owner_user.id == owner_membership.user_id)
        .where(ProjectMembership.user_id == user_id)
        .order_by(Project.is_personal.desc(), Project.name)
    )
    return [
        ProjectWithRole(
            project=project,
            role=ProjectRole(role),
            owner_email=owner_email,
        )
        for project, role, owner_email in result.all()
    ]


async def owner_email_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> str:
    email = await session.scalar(
        select(User.email)
        .join(ProjectMembership, ProjectMembership.user_id == User.id)
        .where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.role == ProjectRole.OWNER,
        )
        .limit(1)
    )
    if email is None:
        raise ProjectNotFoundError(str(project_id))
    return email


async def list_project_ids_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[uuid.UUID]:
    result = await session.execute(
        select(ProjectMembership.project_id).where(ProjectMembership.user_id == user_id)
    )
    return list(result.scalars())


async def list_members(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[MemberRow]:
    result = await session.execute(
        select(ProjectMembership, User.email)
        .join(User, User.id == ProjectMembership.user_id)
        .where(ProjectMembership.project_id == project_id)
        .order_by(User.email)
    )
    return [
        MemberRow(
            user_id=membership.user_id,
            email=email,
            role=ProjectRole(membership.role),
            created_at=membership.created_at,
        )
        for membership, email in result.all()
    ]


async def update_member_role(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role: ProjectRole,
) -> MemberRow:
    await require_owner(session, project_id=project_id, user_id=actor_user_id)
    if role == ProjectRole.OWNER:
        raise ProjectAccessDeniedError("Cannot assign owner role via invitation flow.")
    membership = await require_membership(
        session, project_id=project_id, user_id=target_user_id
    )
    membership.role = role
    await session.commit()
    user = await session.get(User, target_user_id)
    assert user is not None
    return MemberRow(
        user_id=target_user_id,
        email=user.email,
        role=ProjectRole(membership.role),
        created_at=membership.created_at,
    )


async def remove_member(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
) -> None:
    await require_owner(session, project_id=project_id, user_id=actor_user_id)
    project = await require_project(session, project_id)
    if project.is_personal and target_user_id == actor_user_id:
        raise ProjectAccessDeniedError("The personal project owner cannot remove themselves.")
    membership = await get_membership(
        session, project_id=project_id, user_id=target_user_id
    )
    if membership is None:
        raise ProjectMemberNotFoundError(str(project_id), str(target_user_id))
    if is_owner(membership.role):
        owners = list(
            await session.scalars(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == project_id,
                    ProjectMembership.role == ProjectRole.OWNER,
                )
            )
        )
        if len(owners) <= 1 and target_user_id == owners[0].user_id:
            raise ProjectAccessDeniedError("Cannot remove the sole project owner.")
    await session.delete(membership)
    await session.commit()


async def _user_by_email(session: AsyncSession, email: str) -> User:
    normalized = email.strip().lower()
    user = await session.scalar(select(User).where(User.email == normalized))
    if user is None:
        raise UserNotRegisteredError(normalized)
    return user


async def create_invitation(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    invitee_email: str,
    role: ProjectRole,
) -> OutgoingInvitationRow:
    await require_owner(session, project_id=project_id, user_id=actor_user_id)
    if role not in {ProjectRole.VIEWER, ProjectRole.OPERATOR}:
        raise ProjectAccessDeniedError("Invitations may only offer viewer or operator role.")
    invitee = await _user_by_email(session, invitee_email)
    if invitee.id == actor_user_id:
        raise ProjectAccessDeniedError("You cannot invite yourself.")
    existing_member = await get_membership(
        session, project_id=project_id, user_id=invitee.id
    )
    if existing_member is not None:
        raise AlreadyProjectMemberError(invitee.email)
    pending = await session.scalar(
        select(ProjectInvitation).where(
            ProjectInvitation.project_id == project_id,
            ProjectInvitation.invitee_user_id == invitee.id,
            ProjectInvitation.status == InvitationStatus.PENDING,
        )
    )
    if pending is not None:
        raise DuplicateInvitationError(invitee.email)
    invitation = ProjectInvitation(
        project_id=project_id,
        invitee_user_id=invitee.id,
        invited_by_user_id=actor_user_id,
        role=role,
        status=InvitationStatus.PENDING,
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)
    return OutgoingInvitationRow(
        invitation_id=invitation.id,
        invitee_user_id=invitee.id,
        email=invitee.email,
        role=ProjectRole(invitation.role),
        created_at=invitation.created_at,
    )


async def list_pending_invitations_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[OutgoingInvitationRow]:
    result = await session.execute(
        select(ProjectInvitation, User.email)
        .join(User, User.id == ProjectInvitation.invitee_user_id)
        .where(
            ProjectInvitation.project_id == project_id,
            ProjectInvitation.status == InvitationStatus.PENDING,
        )
        .order_by(ProjectInvitation.created_at.desc())
    )
    return [
        OutgoingInvitationRow(
            invitation_id=invitation.id,
            invitee_user_id=invitation.invitee_user_id,
            email=email,
            role=ProjectRole(invitation.role),
            created_at=invitation.created_at,
        )
        for invitation, email in result.all()
    ]


async def list_incoming_invitations_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[IncomingInvitationRow]:
    result = await session.execute(
        select(ProjectInvitation, Project, User.email)
        .join(Project, Project.id == ProjectInvitation.project_id)
        .join(User, User.id == ProjectInvitation.invited_by_user_id)
        .where(
            ProjectInvitation.invitee_user_id == user_id,
            ProjectInvitation.status == InvitationStatus.PENDING,
        )
        .order_by(ProjectInvitation.created_at.desc())
    )
    return [
        IncomingInvitationRow(
            invitation_id=invitation.id,
            project_id=project.id,
            project_name=project.name,
            inviter_email=inviter_email,
            role=ProjectRole(invitation.role),
            created_at=invitation.created_at,
        )
        for invitation, project, inviter_email in result.all()
    ]


async def _load_invitation(
    session: AsyncSession,
    invitation_id: uuid.UUID,
) -> ProjectInvitation:
    invitation = await session.scalar(
        select(ProjectInvitation)
        .where(ProjectInvitation.id == invitation_id)
        .options(selectinload(ProjectInvitation.project))
    )
    if invitation is None:
        raise InvitationNotFoundError(str(invitation_id))
    return invitation


async def accept_invitation(
    session: AsyncSession,
    *,
    invitation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ProjectWithRole:
    invitation = await _load_invitation(session, invitation_id)
    if invitation.invitee_user_id != user_id:
        raise ProjectAccessDeniedError("This invitation is not addressed to you.")
    if invitation.status != InvitationStatus.PENDING:
        raise InvitationAlreadyRespondedError(str(invitation_id))
    existing = await get_membership(
        session, project_id=invitation.project_id, user_id=user_id
    )
    if existing is not None:
        raise AlreadyProjectMemberError("You are already a member of this project.")
    invitation.status = InvitationStatus.ACCEPTED
    invitation.responded_at = _utcnow()
    membership = ProjectMembership(
        project_id=invitation.project_id,
        user_id=user_id,
        role=invitation.role,
    )
    session.add(membership)
    await session.commit()
    project = await require_project(session, invitation.project_id)
    return ProjectWithRole(
        project=project,
        role=ProjectRole(invitation.role),
        owner_email=await owner_email_for_project(session, project.id),
    )


async def reject_invitation(
    session: AsyncSession,
    *,
    invitation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    invitation = await _load_invitation(session, invitation_id)
    if invitation.invitee_user_id != user_id:
        raise ProjectAccessDeniedError("This invitation is not addressed to you.")
    if invitation.status != InvitationStatus.PENDING:
        raise InvitationAlreadyRespondedError(str(invitation_id))
    invitation.status = InvitationStatus.REJECTED
    invitation.responded_at = _utcnow()
    await session.commit()


async def cancel_invitation(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    invitation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    await require_owner(session, project_id=project_id, user_id=actor_user_id)
    invitation = await _load_invitation(session, invitation_id)
    if invitation.project_id != project_id:
        raise InvitationNotFoundError(str(invitation_id))
    if invitation.status != InvitationStatus.PENDING:
        raise InvitationAlreadyRespondedError(str(invitation_id))
    invitation.status = InvitationStatus.CANCELLED
    invitation.responded_at = _utcnow()
    await session.commit()


async def get_personal_project_id(
    session: AsyncSession,
    user: User,
) -> uuid.UUID:
    if user.personal_project_id is not None:
        return user.personal_project_id
    project = await ensure_personal_workspace(session, user)
    return project.id


async def create_shared_project(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    name: str,
) -> ProjectWithRole:
    trimmed_name = name.strip()
    if not trimmed_name:
        raise ProjectAccessDeniedError("Team name cannot be empty.")

    organization = Organization(name=trimmed_name)
    session.add(organization)
    await session.flush()

    project = Project(
        organization_id=organization.id,
        name=trimmed_name,
        is_personal=False,
    )
    session.add(project)
    await session.flush()

    membership = ProjectMembership(
        project_id=project.id,
        user_id=user_id,
        role=ProjectRole.OWNER,
    )
    session.add(membership)
    await session.commit()
    await session.refresh(project)
    return ProjectWithRole(
        project=project,
        role=ProjectRole.OWNER,
        owner_email=await owner_email_for_project(session, project.id),
    )


async def leave_project(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    project = await require_project(session, project_id)
    membership = await require_membership(
        session, project_id=project_id, user_id=user_id
    )
    if is_owner(membership.role):
        if project.is_personal:
            raise ProjectAccessDeniedError("You cannot leave your personal workspace.")
        raise ProjectAccessDeniedError(
            "Team owners cannot leave. Remove members or delete the team instead."
        )
    await session.delete(membership)
    await session.commit()
