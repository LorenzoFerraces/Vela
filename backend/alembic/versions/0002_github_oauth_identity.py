"""Add GitHub OAuth identity columns (token at rest, profile fields).

Revision ID: 0002_github_oauth_identity
Revises: 0001_initial_auth
Create Date: 2026-05-07

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_github_oauth_identity"
down_revision: str | Sequence[str] | None = "0001_initial_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_oauth_identities",
        sa.Column("username", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "user_oauth_identities",
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "user_oauth_identities",
        sa.Column("scopes", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "user_oauth_identities",
        sa.Column("access_token_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "user_oauth_identities",
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "user_oauth_identities",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_oauth_provider_user",
        "user_oauth_identities",
        ["provider", "user_id"],
    )

    # Drop the server default after backfilling existing rows; new inserts go
    # through SQLAlchemy and supply their own timestamps.
    op.alter_column("user_oauth_identities", "connected_at", server_default=None)
    op.alter_column("user_oauth_identities", "updated_at", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "uq_oauth_provider_user", "user_oauth_identities", type_="unique"
    )
    op.drop_column("user_oauth_identities", "updated_at")
    op.drop_column("user_oauth_identities", "connected_at")
    op.drop_column("user_oauth_identities", "access_token_encrypted")
    op.drop_column("user_oauth_identities", "scopes")
    op.drop_column("user_oauth_identities", "avatar_url")
    op.drop_column("user_oauth_identities", "username")
