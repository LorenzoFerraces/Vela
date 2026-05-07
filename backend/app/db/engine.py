"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import os
import sys
from functools import lru_cache

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from dotenv import load_dotenv

load_dotenv(override=True)


def _database_url() -> str:
    url = os.environ.get("VELA_DATABASE_URL", "").strip()
    if not url:
        msg = (
            "VELA_DATABASE_URL is not set. "
            "Configure backend/.env with a SQLAlchemy async URL "
            "(e.g. postgresql+asyncpg://vela:vela@127.0.0.1:15432/Vela)."
        )
        raise RuntimeError(msg)
    return url


def _database_url_for_engine() -> str:
    """Return URL suitable for client connections.

    On Windows, ``localhost`` often resolves to ``::1`` first while Docker Desktop
    publishes Postgres on IPv4 only, which can cause reset / half-open connections.
    """
    url = _database_url()
    if sys.platform != "win32":
        return url
    try:
        parsed = make_url(url)
    except Exception:
        return url
    if parsed.host != "localhost":
        return url
    # str(URL) masks passwords as "***"; connection strings need the real secret.
    return parsed.set(host="127.0.0.1").render_as_string(hide_password=False)


def sync_database_url_for_alembic() -> str:
    """Return a **synchronous** DB URL for Alembic.

    ``alembic upgrade`` uses ``psycopg`` (sync). The FastAPI app keeps
    ``postgresql+asyncpg`` via :func:`create_async_engine_from_env`, which is
    unreliable for some Windows + Docker Desktop setups even when ``psql`` works.
    """
    url = _database_url_for_engine()
    try:
        parsed = make_url(url)
    except Exception:
        return url
    if parsed.drivername == "postgresql+asyncpg":
        return parsed.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    return url


def create_async_engine_from_env() -> AsyncEngine:
    """Build a fresh async engine from the current environment."""
    url = _database_url_for_engine()
    kwargs: dict[str, object] = {"pool_pre_ping": True, "future": True}
    if "+asyncpg" in url:
        kwargs["connect_args"] = {"timeout": 60}
    return create_async_engine(url, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Process-wide async engine."""
    return create_async_engine_from_env()


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Process-wide async session factory."""
    return create_session_factory(get_engine())
