"""add team compute quotas

Revision ID: 0026_add_team_compute_quotas
Revises: 0025_externalized_state
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_add_team_compute_quotas"
down_revision = "0025_externalized_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("max_running_containers", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("max_cpu_millicores", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("max_memory_bytes", sa.BigInteger(), nullable=True))
    op.add_column("projects", sa.Column("max_deploys_per_hour", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "max_deploys_per_hour")
    op.drop_column("projects", "max_memory_bytes")
    op.drop_column("projects", "max_cpu_millicores")
    op.drop_column("projects", "max_running_containers")
