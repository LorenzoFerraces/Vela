"""Widen organizations.name for long email-derived workspace names.

Revision ID: 0010_organization_name_320
Revises: 0009_deployment_project_id
Create Date: 2026-06-13

"""
from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_organization_name_320"
down_revision: str | Sequence[str] | None = "0009_deployment_project_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "organizations",
        "name",
        existing_type=sa.String(length=255),
        type_=sa.String(length=320),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "organizations",
        "name",
        existing_type=sa.String(length=320),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
