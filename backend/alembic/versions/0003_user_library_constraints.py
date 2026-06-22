"""User library: dockerfile updated_at and per-owner uniqueness.

Revision ID: 0003_user_library_constraints
Revises: 0002_github_oauth_identity
Create Date: 2026-05-19

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_user_library_constraints"
down_revision: str | Sequence[str] | None = "0002_github_oauth_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Apply schema changes: add an updated_at timestamp to dockerfiles and enforce owner-scoped uniqueness for dockerfiles and images.

    Adds a timezone-aware `updated_at` column to `dockerfiles`, backfills it from `created_at`, and then makes it non-nullable. Creates a unique constraint `uq_dockerfiles_owner_name` on `dockerfiles(owner_id, name)` and `uq_images_owner_ref` on `images(owner_id, ref)`.
    """
    op.add_column(
        "dockerfiles",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text("UPDATE dockerfiles SET updated_at = created_at"))
    op.alter_column("dockerfiles", "updated_at", nullable=False)

    op.create_unique_constraint(
        "uq_dockerfiles_owner_name",
        "dockerfiles",
        ["owner_id", "name"],
    )
    op.create_unique_constraint(
        "uq_images_owner_ref",
        "images",
        ["owner_id", "ref"],
    )


def downgrade() -> None:
    """
    Revert the migration: remove the unique constraints on images(owner_id, ref) and dockerfiles(owner_id, name), and drop the dockerfiles.updated_at column.
    """
    op.drop_constraint("uq_images_owner_ref", "images", type_="unique")
    op.drop_constraint("uq_dockerfiles_owner_name", "dockerfiles", type_="unique")
    op.drop_column("dockerfiles", "updated_at")
