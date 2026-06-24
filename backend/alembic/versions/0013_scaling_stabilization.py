"""Add stabilization windows to scaling_policies.

Revision ID: 0013_scaling_stabilization
Revises: 0012_scaling_policies
Create Date: 2026-06-24

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_scaling_stabilization"
down_revision: str | Sequence[str] | None = "0012_scaling_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scaling_policies",
        sa.Column(
            "scale_up_stabilization_seconds",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
    )
    op.add_column(
        "scaling_policies",
        sa.Column(
            "scale_down_stabilization_seconds",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
    )
    op.add_column(
        "scaling_policies",
        sa.Column("scale_up_condition_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scaling_policies",
        sa.Column("scale_down_condition_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("scaling_policies", "scale_up_stabilization_seconds", server_default=None)
    op.alter_column("scaling_policies", "scale_down_stabilization_seconds", server_default=None)


def downgrade() -> None:
    op.drop_column("scaling_policies", "scale_down_condition_since")
    op.drop_column("scaling_policies", "scale_up_condition_since")
    op.drop_column("scaling_policies", "scale_down_stabilization_seconds")
    op.drop_column("scaling_policies", "scale_up_stabilization_seconds")
