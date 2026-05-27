"""Deploy config preferences and deployment history.

Revision ID: 0005_deploy_config_and_history
Revises: 0004_drop_images
Create Date: 2026-05-25

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_deploy_config_and_history"
down_revision: str | Sequence[str] | None = "0004_drop_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("ai_prefill_preferences", sa.JSON(), nullable=True),
    )
    op.create_table(
        "deployment_records",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("container_id", sa.String(length=128), nullable=False),
        sa.Column("container_name", sa.String(length=128), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=2048), nullable=False),
        sa.Column("git_branch", sa.String(length=256), nullable=True),
        sa.Column("image_tag", sa.String(length=512), nullable=False),
        sa.Column("container_port", sa.Integer(), nullable=False),
        sa.Column("env_vars", sa.JSON(), nullable=False),
        sa.Column("command", sa.JSON(), nullable=True),
        sa.Column("dockerfile_snapshot", sa.Text(), nullable=True),
        sa.Column("public_url", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deployment_records_user_id_created_at",
        "deployment_records",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deployment_records_user_id_created_at",
        table_name="deployment_records",
    )
    op.drop_table("deployment_records")
    op.drop_column("users", "ai_prefill_preferences")
