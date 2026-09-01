"""add volumes and scaling_policy to stack_services

Revision ID: ea51f2f64578
Revises: 0014_stacks
Create Date: 2026-07-31 21:19:16.201021

"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'ea51f2f64578'
down_revision: str | Sequence[str] | None = '0014_stacks'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('stack_services', sa.Column('volumes', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('stack_services', sa.Column('scaling_policy', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('stack_services', 'scaling_policy')
    op.drop_column('stack_services', 'volumes')
