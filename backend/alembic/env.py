"""Alembic environment.

Online migrations use a **synchronous** ``psycopg`` engine. The API uses
``asyncpg`` via :func:`~app.db.engine.create_async_engine_from_env`.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

import app.bootstrap_env  # noqa: F401 — load backend/.env before reading env vars.
from app.db.base import Base
from app.db import models  # noqa: F401 — register models on Base.metadata.
from app.db.engine import sync_database_url_for_alembic

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection."""
    url = sync_database_url_for_alembic()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database (sync driver)."""
    connectable = create_engine(sync_database_url_for_alembic(), pool_pre_ping=True)
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
