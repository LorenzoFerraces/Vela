"""Add stacks, stack_services, stack_compositions tables and deployment_records.stack_id.

Revision ID: 0014_stacks
Revises: 0013_scaling_stabilization
Create Date: 2026-07-31

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_stacks"
down_revision: str | Sequence[str] | None = "0013_scaling_stabilization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stacks",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("network_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_stacks_project_name"),
        sa.UniqueConstraint("network_name", name="uq_stacks_network_name"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_stacks_project_id"), "stacks", ["project_id"], unique=False)

    op.create_table(
        "stack_services",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stack_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("service_name", sa.String(128), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(2048), nullable=False),
        sa.Column("container_port", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("env_vars", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("command", sa.JSON(), nullable=True),
        sa.Column("public_route", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("depends_on", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stack_id", "service_name", name="uq_stack_services_stack_name"),
        sa.ForeignKeyConstraint(["stack_id"], ["stacks.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_stack_services_stack_id"), "stack_services", ["stack_id"], unique=False)

    op.create_table(
        "stack_compositions",
        sa.Column("parent_stack_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("child_stack_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("parent_stack_id", "child_stack_id"),
        sa.UniqueConstraint("parent_stack_id", "child_stack_id", name="uq_stack_compositions_parent_child"),
        sa.ForeignKeyConstraint(["parent_stack_id"], ["stacks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_stack_id"], ["stacks.id"], ondelete="CASCADE"),
    )

    op.add_column(
        "deployment_records",
        sa.Column("stack_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_deployment_records_stack_id", "deployment_records",
        "stacks", ["stack_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(op.f("ix_deployment_records_stack_id"), "deployment_records", ["stack_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_deployment_records_stack_id"), table_name="deployment_records")
    op.drop_constraint("fk_deployment_records_stack_id", "deployment_records", type_="foreignkey")
    op.drop_column("deployment_records", "stack_id")
    op.drop_index(op.f("ix_stack_services_stack_id"), table_name="stack_services")
    op.drop_table("stack_compositions")
    op.drop_table("stack_services")
    op.drop_index(op.f("ix_stacks_project_id"), table_name="stacks")
    op.drop_table("stacks")
