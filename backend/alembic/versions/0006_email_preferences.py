"""Add email_preferences table for notification settings.

Revision ID: 0006_email_preferences
Revises: 0005_deploy_config_and_history
Create Date: 2026-06-01

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_email_preferences"
down_revision: str | Sequence[str] | None = "0005_deploy_config_and_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("alerts_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("alert_types", sa.JSON(), nullable=False, server_default='["stop", "failure", "unhealthy"]'),
        sa.Column("alert_frequency", sa.String(length=32), nullable=False, server_default="immediate"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_email_preferences_user_id"),
    )
    op.create_index(
        "ix_email_preferences_user_id",
        "email_preferences",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_preferences_user_id", table_name="email_preferences")
    op.drop_table("email_preferences")
