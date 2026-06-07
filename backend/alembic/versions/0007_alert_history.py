"""Add alert_history table for deduplication and audit trail.

Revision ID: 0007_alert_history
Revises: 0006_email_preferences
Create Date: 2026-06-01

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_alert_history"
down_revision: str | Sequence[str] | None = "0006_email_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_history",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("container_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("alert_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("email_sent_to", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="sent"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_history_user_id",
        "alert_history",
        ["user_id"],
    )
    op.create_index(
        "ix_alert_history_container_id",
        "alert_history",
        ["container_id"],
    )
    op.create_index(
        "ix_alert_history_alert_hash",
        "alert_history",
        ["alert_hash"],
    )
    op.create_index(
        "ix_alert_history_sent_at",
        "alert_history",
        ["sent_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_alert_history_sent_at", table_name="alert_history")
    op.drop_index("ix_alert_history_alert_hash", table_name="alert_history")
    op.drop_index("ix_alert_history_container_id", table_name="alert_history")
    op.drop_index("ix_alert_history_user_id", table_name="alert_history")
    op.drop_table("alert_history")
