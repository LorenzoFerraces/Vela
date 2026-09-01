"""merge console-utils migration heads

Revision ID: 0017_merge_console_utils
Revises: 0016_build_override, 0016_container_logs
Create Date: 2026-08-15

"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0017_merge_console_utils"
down_revision: str | Sequence[str] | None = ("0016_build_override", "0016_container_logs")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
