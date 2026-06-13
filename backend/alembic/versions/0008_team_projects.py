"""Team projects: organizations, projects, memberships, invitations.

Revision ID: 0008_team_projects
Revises: 0007_alert_history
Create Date: 2026-06-10

"""
from __future__ import annotations

import uuid
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_team_projects"
down_revision: str | Sequence[str] | None = "0007_alert_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_personal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name="fk_projects_organization",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_projects_org_name"),
    )
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    op.create_table(
        "project_memberships",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name="fk_project_memberships_project",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_project_memberships_user",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
    )
    op.create_index("ix_project_memberships_user_id", "project_memberships", ["user_id"])
    op.create_index("ix_project_memberships_project_id", "project_memberships", ["project_id"])
    op.create_table(
        "project_invitations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("invitee_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name="fk_project_invitations_project",
        ),
        sa.ForeignKeyConstraint(
            ["invitee_user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_project_invitations_invitee",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_project_invitations_invited_by",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_invitations_invitee_status",
        "project_invitations",
        ["invitee_user_id", "status"],
    )
    op.create_index(
        "ix_project_invitations_project_status",
        "project_invitations",
        ["project_id", "status"],
    )
    op.add_column(
        "users",
        sa.Column("personal_project_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_personal_project",
        "users",
        "projects",
        ["personal_project_id"],
        ["id"],
        ondelete="SET NULL",
    )

    _backfill_personal_workspaces()


def _backfill_personal_workspaces() -> None:
    bind = op.get_bind()
    users = bind.execute(sa.text("SELECT id, email, created_at FROM users")).fetchall()
    for user_row in users:
        user_id = user_row[0]
        email = user_row[1]
        created_at = user_row[2]
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        membership_id = uuid.uuid4()
        org_name = f"{email} workspace"
        bind.execute(
            sa.text(
                "INSERT INTO organizations (id, name, created_at) "
                "VALUES (:id, :name, :created_at)"
            ),
            {"id": org_id, "name": org_name, "created_at": created_at},
        )
        bind.execute(
            sa.text(
                "INSERT INTO projects (id, organization_id, name, is_personal, created_at) "
                "VALUES (:id, :organization_id, :name, :is_personal, :created_at)"
            ),
            {
                "id": project_id,
                "organization_id": org_id,
                "name": "Personal",
                "is_personal": True,
                "created_at": created_at,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO project_memberships (id, project_id, user_id, role, created_at) "
                "VALUES (:id, :project_id, :user_id, :role, :created_at)"
            ),
            {
                "id": membership_id,
                "project_id": project_id,
                "user_id": user_id,
                "role": "owner",
                "created_at": created_at,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE users SET personal_project_id = :project_id WHERE id = :user_id"
            ),
            {"project_id": project_id, "user_id": user_id},
        )


def downgrade() -> None:
    op.drop_constraint("fk_users_personal_project", "users", type_="foreignkey")
    op.drop_column("users", "personal_project_id")
    op.drop_index("ix_project_invitations_project_status", table_name="project_invitations")
    op.drop_index("ix_project_invitations_invitee_status", table_name="project_invitations")
    op.drop_table("project_invitations")
    op.drop_index("ix_project_memberships_project_id", table_name="project_memberships")
    op.drop_index("ix_project_memberships_user_id", table_name="project_memberships")
    op.drop_table("project_memberships")
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_table("projects")
    op.drop_table("organizations")
