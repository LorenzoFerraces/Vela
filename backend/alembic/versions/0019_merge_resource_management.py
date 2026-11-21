"""merge resource-management migrations with the console-utils merge

Revision ID: 0019_merge_resource_management
Revises: 0018_project_storage_quota, 0018_deployment_records_cid_idx
Create Date: 2026-08-18

"""
from __future__ import annotations

from collections.abc import Sequence

revision: str = "0019_merge_resource_management"
down_revision: str | Sequence[str] | None = (
    "0018_project_storage_quota",
    "0018_deployment_records_cid_idx",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the resource-management heads; no schema change."""


def downgrade() -> None:
    """Merge point; nothing to undo."""
