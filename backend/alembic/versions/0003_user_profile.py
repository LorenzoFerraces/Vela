"""Add user profile fields (display name, pronouns, avatar).

Revision ID: 0003_user_profile
Revises: 0002_github_oauth_identity
Create Date: 2026-06-17

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_user_profile"
down_revision: str | Sequence[str] | None = "0002_github_oauth_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("display_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("pronouns", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("avatar_object_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("avatar_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_updated_at")
    op.drop_column("users", "avatar_object_key")
    op.drop_column("users", "pronouns")
    op.drop_column("users", "display_name")
