"""Add project_id to deployment_records.

Revision ID: 0009_deployment_project_id
Revises: 0008_team_projects
Create Date: 2026-06-10

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_deployment_project_id"
down_revision: str | Sequence[str] | None = "0008_team_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deployment_records",
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_deployment_records_project",
        "deployment_records",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_deployment_records_project_id_created_at",
        "deployment_records",
        ["project_id", "created_at"],
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE deployment_records "
            "SET project_id = ("
            "  SELECT personal_project_id FROM users WHERE users.id = deployment_records.user_id"
            ") "
            "WHERE project_id IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deployment_records_project_id_created_at",
        table_name="deployment_records",
    )
    op.drop_constraint("fk_deployment_records_project", "deployment_records", type_="foreignkey")
    op.drop_column("deployment_records", "project_id")
