"""group c lifecycle

Revision ID: 0027_group_c_lifecycle
Revises: 0026_add_team_compute_quotas
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_group_c_lifecycle"
down_revision = "0026_add_team_compute_quotas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secrets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "name"),
        sa.UniqueConstraint("project_id", "name"),
    )
    op.create_table(
        "secret_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("secret_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["secret_id"], ["secrets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("secret_id", "version"),
    )
    op.create_table(
        "github_app_installs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("app_id", sa.String(64), nullable=False),
        sa.Column("slug", sa.String(128), nullable=True),
        sa.Column("private_key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("webhook_secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "github_app_installation_ids",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("app_install_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.String(64), nullable=False),
        sa.Column("account_login", sa.String(128), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["app_install_id"], ["github_app_installs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_install_id", "project_id"),
    )
    op.create_table(
        "github_webhook_configs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("repo_full_name", sa.String(256), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("branch_filters", sa.JSON(), nullable=False),
        sa.Column("preview_enabled", sa.Boolean(), nullable=False),
        sa.Column("preview_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "github_webhook_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("repo_full_name", sa.String(256), nullable=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=True),
        sa.Column("branch", sa.String(256), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("is_fork", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id"),
    )
    op.create_index("ix_github_webhook_deliveries_received_at", "github_webhook_deliveries", ["received_at"])
    op.create_table(
        "preview_deploys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("repo_full_name", sa.String(256), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(64), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=True),
        sa.Column("container_name", sa.String(128), nullable=True),
        sa.Column("route_host", sa.String(253), nullable=True),
        sa.Column("public_url", sa.String(512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "repo_full_name", "pr_number"),
    )
    op.create_index("ix_preview_deploys_expires_at", "preview_deploys", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_preview_deploys_expires_at", table_name="preview_deploys")
    op.drop_table("preview_deploys")
    op.drop_index("ix_github_webhook_deliveries_received_at", table_name="github_webhook_deliveries")
    op.drop_table("github_webhook_deliveries")
    op.drop_table("github_webhook_configs")
    op.drop_table("github_app_installation_ids")
    op.drop_table("github_app_installs")
    op.drop_table("secret_versions")
    op.drop_table("secrets")
