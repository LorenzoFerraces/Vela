"""Add container_metrics table for time-series resource data.

Revision ID: 0017_container_metrics
Revises: 0016_build_override
Create Date: 2026-08-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_container_metrics"
down_revision: str | Sequence[str] | None = "0016_build_override"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "container_metrics",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_usage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_percent", sa.Float(), nullable=False),
        sa.Column("network_rx_bytes", sa.BigInteger(), nullable=False),
        sa.Column("network_tx_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_container_metrics_container_timestamp",
        "container_metrics",
        ["container_id", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_container_metrics_container_timestamp", table_name="container_metrics"
    )
    op.drop_table("container_metrics")
