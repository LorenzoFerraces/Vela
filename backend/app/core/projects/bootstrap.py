"""Ensure each user has a personal organization and project."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.projects.enums import ProjectRole
from app.core.projects.names import personal_organization_name
from app.db.models import Organization, Project, ProjectMembership, User


async def ensure_personal_workspace(session: AsyncSession, user: User) -> Project:
    """Create org, personal project, and owner membership if missing; set user.personal_project_id."""
    locked_user = await session.scalar(
        select(User).where(User.id == user.id).with_for_update()
    )
    if locked_user is None:
        raise ValueError(f"User {user.id} not found")
    user = locked_user

    if user.personal_project_id is not None:
        project = await session.get(Project, user.personal_project_id)
        if project is not None:
            return project

    organization = Organization(name=personal_organization_name(user.email))
    session.add(organization)
    await session.flush()

    project = Project(
        organization_id=organization.id,
        name="Personal",
        is_personal=True,
    )
    session.add(project)
    await session.flush()

    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        role=ProjectRole.OWNER,
    )
    session.add(membership)

    user.personal_project_id = project.id
    await session.commit()
    await session.refresh(user)
    await session.refresh(project)
    return project
