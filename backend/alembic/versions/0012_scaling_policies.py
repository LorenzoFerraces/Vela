"""Add scaling_policies table for horizontal auto-scaling.

Revision ID: 0012_scaling_policies
Revises: 0011_user_profile
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_scaling_policies"
down_revision: str | Sequence[str] | None = "0011_user_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scaling_policies",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("container_name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("min_replicas", sa.Integer(), nullable=False),
        sa.Column("max_replicas", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("scale_up_threshold", sa.Float(), nullable=False),
        sa.Column("scale_down_threshold", sa.Float(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("last_scaled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_scaling_policies_container_name",
        "scaling_policies",
        ["container_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_scaling_policies_container_name", table_name="scaling_policies")
    op.drop_table("scaling_policies")
