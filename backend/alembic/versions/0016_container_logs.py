"""Add container_logs table for aggregated container log storage.

Revision ID: 0016_container_logs
Revises: 0014_audit_log
Create Date: 2026-08-03

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_container_logs"
down_revision: str | Sequence[str] | None = "0014_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "container_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("container_id", sa.String(length=128), nullable=False),
        sa.Column("container_name", sa.String(length=128), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "level",
            sa.String(length=16),
            nullable=False,
            server_default="info",
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_container_logs_container_id", "container_logs", ["container_id"])
    op.create_index("ix_container_logs_container_name", "container_logs", ["container_name"])
    op.create_index(
        "ix_container_logs_container_timestamp",
        "container_logs",
        ["container_id", "timestamp"],
    )
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute(
            "CREATE INDEX ix_container_logs_fts ON container_logs USING gin (message gin_trgm_ops)"
        )
    except Exception:
        pass


def downgrade() -> None:
    op.drop_index("ix_container_logs_container_timestamp", table_name="container_logs")
    op.drop_index("ix_container_logs_container_name", table_name="container_logs")
    op.drop_index("ix_container_logs_container_id", table_name="container_logs")
    op.drop_table("container_logs")
