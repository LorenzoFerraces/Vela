"""add project storage quota and nullable alert container id

Revision ID: 0018_project_storage_quota
Revises: 0017_container_metrics
Create Date: 2026-08-16

"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0018_project_storage_quota"
down_revision: str | Sequence[str] | None = "0017_container_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("storage_quota_bytes", sa.BigInteger(), nullable=True),
    )
    with op.batch_alter_table("alert_history") as batch_op:
        batch_op.alter_column(
            "container_id",
            existing_type=sa.String(length=128),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("alert_history") as batch_op:
        batch_op.alter_column(
            "container_id",
            existing_type=sa.String(length=128),
            nullable=False,
        )
    op.drop_column("projects", "storage_quota_bytes")
