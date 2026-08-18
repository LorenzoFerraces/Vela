"""merge resource-management migrations with the console-utils merge

Revision ID: 0019_merge_resource_management
Revises: 0017_merge_console_utils, 0018_project_storage_quota
Create Date: 2026-08-18

"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0019_merge_resource_management"
down_revision: str | Sequence[str] | None = ("0017_merge_console_utils", "0018_project_storage_quota")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
