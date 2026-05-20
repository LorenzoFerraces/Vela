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
    op.drop_constraint("uq_images_owner_ref", "images", type_="unique")
    op.drop_constraint("uq_dockerfiles_owner_name", "dockerfiles", type_="unique")
    op.drop_column("dockerfiles", "updated_at")
