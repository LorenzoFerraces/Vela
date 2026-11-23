"""externalized state

Revision ID: 0025_externalized_state
Revises: 0024_api_token_lifecycle
"""
import sqlalchemy as sa

from alembic import op

revision = "0025_externalized_state"
down_revision = "0024_api_token_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deploy_jobs",
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_label", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("phase", sa.String(64), nullable=False),
        sa.Column("phase_detail", sa.Text(), nullable=True),
        sa.Column("services", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_deploy_jobs_project_id", "deploy_jobs", ["project_id"])
    op.create_index("ix_deploy_jobs_finished_at", "deploy_jobs", ["finished_at"])

    op.create_table(
        "traffic_routes",
        sa.Column("route_id", sa.String(128), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("path_prefix", sa.String(512), nullable=False),
        sa.Column("backend_servers", sa.JSON(), nullable=False),
        sa.Column("tls_enabled", sa.Boolean(), nullable=False),
        sa.Column("entrypoints", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("route_id"),
    )

    op.create_table(
        "ws_tickets",
        sa.Column("ticket", sa.String(128), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("ticket"),
    )
    op.create_index("ix_ws_tickets_container_id", "ws_tickets", ["container_id"])


def downgrade() -> None:
    op.drop_index("ix_ws_tickets_container_id", table_name="ws_tickets")
    op.drop_table("ws_tickets")
    op.drop_table("traffic_routes")
    op.drop_index("ix_deploy_jobs_finished_at", table_name="deploy_jobs")
    op.drop_index("ix_deploy_jobs_project_id", table_name="deploy_jobs")
    op.drop_table("deploy_jobs")
