"""add git_branch to stack_services

Revision ID: 0015_stack_service_git_branch
Revises: ea51f2f64578
Create Date: 2026-08-11

"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0015_stack_service_git_branch"
down_revision: str | Sequence[str] | None = "ea51f2f64578"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stack_services",
        sa.Column("git_branch", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stack_services", "git_branch")
