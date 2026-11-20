"""Add expiry, last-used and scope to API tokens.

Revision ID: 0024_api_token_lifecycle
Revises: 0023_deploy_config_snapshot
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0024_api_token_lifecycle"
down_revision: str | None = "0023_deploy_config_snapshot"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("api_tokens", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_tokens", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "api_tokens",
        sa.Column("scope", sa.String(32), nullable=False, server_default="full"),
    )


def downgrade() -> None:
    op.drop_column("api_tokens", "scope")
    op.drop_column("api_tokens", "last_used_at")
    op.drop_column("api_tokens", "expires_at")
