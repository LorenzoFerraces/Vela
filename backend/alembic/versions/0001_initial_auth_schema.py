"""Initial auth schema (users, OAuth identities, images, dockerfiles).

Revision ID: 0001_initial_auth
Revises:
Create Date: 2026-05-01

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_auth"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "user_oauth_identities",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_oauth_user"
        ),
        sa.UniqueConstraint(
            "provider", "provider_subject", name="uq_oauth_provider_subject"
        ),
    )
    op.create_index(
        "ix_user_oauth_identities_user_id",
        "user_oauth_identities",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "images",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("ref", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], ondelete="CASCADE", name="fk_images_owner"
        ),
    )
    op.create_index("ix_images_owner_id", "images", ["owner_id"], unique=False)

    op.create_table(
        "dockerfiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("contents", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], ondelete="CASCADE", name="fk_dockerfiles_owner"
        ),
    )
    op.create_index(
        "ix_dockerfiles_owner_id", "dockerfiles", ["owner_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_dockerfiles_owner_id", table_name="dockerfiles")
    op.drop_table("dockerfiles")
    op.drop_index("ix_images_owner_id", table_name="images")
    op.drop_table("images")
    op.drop_index(
        "ix_user_oauth_identities_user_id", table_name="user_oauth_identities"
    )
    op.drop_table("user_oauth_identities")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
