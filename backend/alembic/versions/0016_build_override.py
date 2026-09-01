"""add build_override to stack_services and deployment_records

Revision ID: 0016_build_override
Revises: 0015_stack_service_git_branch
Create Date: 2026-08-11

"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0016_build_override"
down_revision: str | Sequence[str] | None = "0015_stack_service_git_branch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stack_services", sa.Column("build_override", sa.JSON(), nullable=True))
    op.add_column("deployment_records", sa.Column("build_override", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployment_records", "build_override")
    op.drop_column("stack_services", "build_override")
