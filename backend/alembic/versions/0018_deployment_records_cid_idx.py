"""Add index on deployment_records.container_id.

Revision ID: 0018_deployment_records_cid_idx
Revises: 0017_merge_console_utils
Create Date: 2026-09-01

"""
from __future__ import annotations

from typing import Sequence

from alembic import op


revision: str = "0018_deployment_records_cid_idx"
down_revision: str | Sequence[str] | None = "0017_merge_console_utils"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_deployment_records_container_id", "deployment_records", ["container_id"])


def downgrade() -> None:
    op.drop_index("ix_deployment_records_container_id", table_name="deployment_records")
