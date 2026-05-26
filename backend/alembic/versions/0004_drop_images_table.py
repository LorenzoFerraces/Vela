"""Drop per-user saved image refs table (images).

Revision ID: 0004_drop_images
Revises: 0003_user_library_constraints
Create Date: 2026-05-18

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_drop_images"
down_revision: str | Sequence[str] | None = "0003_user_library_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Drop the "images" table from the database schema.
    
    This migration step removes the images table and all data it contains.
    """
    op.drop_table("images")


def downgrade() -> None:
    """
    Recreates the `images` table with its original schema, constraints, and index.
    
    Creates an `images` table containing:
    - `id`: UUID primary key, not nullable
    - `owner_id`: UUID, not nullable, foreign key to `users.id` with ON DELETE CASCADE (constraint name `fk_images_owner`)
    - `ref`: string (max length 512), not nullable
    - `created_at`: timezone-aware DateTime, not nullable
    
    Also adds a unique constraint on (`owner_id`, `ref`) named `uq_images_owner_ref` and a non-unique index `ix_images_owner_id` on `owner_id`.
    """
    op.create_table(
        "images",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("ref", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], ondelete="CASCADE", name="fk_images_owner"
        ),
        sa.UniqueConstraint("owner_id", "ref", name="uq_images_owner_ref"),
    )
    op.create_index("ix_images_owner_id", "images", ["owner_id"], unique=False)
