"""Persist the full deploy config used to create a container.

Revision ID: 0023_deploy_config_snapshot
Revises: 0022_api_tokens
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0023_deploy_config_snapshot"
down_revision: str | None = "0022_api_tokens"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("deployment_records", sa.Column("deploy_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployment_records", "deploy_config")
