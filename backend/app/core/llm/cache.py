"""Commit-keyed LLM result cache, avoids paying for repeat analyses of unchanged repos."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_MAX_ENTRIES = 500
_CACHE_DIR_ENV = "VELA_LLM_CACHE_DIR"
_DB_FILENAME = "llm_cache.db"
_LEGACY_FILE_GLOB = "llm_analysis_*.json"
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS llm_cache ("
    "kind TEXT, version TEXT, commit_sha TEXT, payload TEXT, ts REAL, "
    "PRIMARY KEY (kind, version, commit_sha))"
)


def _cache_root() -> Path:
    override = os.environ.get(_CACHE_DIR_ENV, "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "data"


def _enabled() -> bool:
    return os.environ.get("VELA_LLM_CACHE", "1").strip() != "0"


_ensure_lock = threading.Lock()
_ensured_root: Path | None = None


def _ensure_db() -> Path:
    # Runs once per process per cache root; re-runs only if the root changes (tests swap dirs)
    global _ensured_root
    root = _cache_root()
    db_path = root / _DB_FILENAME
    if _ensured_root == root:
        return db_path
    with _ensure_lock:
        if _ensured_root == root:
            return db_path
        root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(_CREATE_TABLE)
            _migrate_legacy_files(conn, root)
            conn.commit()
        finally:
            conn.close()
        _ensured_root = root
    return db_path


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_ensure_db())
    try:
        yield conn
    finally:
        conn.close()


def _migrate_legacy_files(conn: sqlite3.Connection, root: Path) -> None:
    for path in sorted(root.glob(_LEGACY_FILE_GLOB)):
        kind = path.stem.removeprefix("llm_analysis_")
        data: object
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                timestamp = value.get("ts")
                payload = value.get("payload")
                if not isinstance(timestamp, (int, float)):
                    continue
                if not isinstance(payload, dict):
                    continue
                version, separator, commit = key.partition(":")
                if not separator or not commit:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO llm_cache "
                    "(kind, version, commit_sha, payload, ts) VALUES (?, ?, ?, ?, ?)",
                    (kind, version, commit, json.dumps(payload), float(timestamp)),
                )
        path.unlink()


def _load_cached_sync(kind: str, commit: str, version: str) -> dict | None:
    if not _enabled() or not commit:
        return None
    try:
        with _connection() as conn:
            row = conn.execute(
                "SELECT payload FROM llm_cache "
                "WHERE kind = ? AND version = ? AND commit_sha = ?",
                (kind, version, commit),
            ).fetchone()
    except (OSError, sqlite3.Error):
        return None
    if row is None:
        return None
    try:
        payload = json.loads(row[0])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


async def load_cached(kind: str, commit: str, version: str) -> dict | None:
    return await asyncio.to_thread(_load_cached_sync, kind, commit, version)


def _delete_cached_sync(kind: str, commit: str, version: str) -> None:
    if not _enabled() or not commit:
        return
    try:
        with _connection() as conn:
            conn.execute(
                "DELETE FROM llm_cache WHERE kind = ? AND version = ? AND commit_sha = ?",
                (kind, version, commit),
            )
            conn.commit()
    except (OSError, sqlite3.Error):
        return


async def delete_cached(kind: str, commit: str, version: str) -> None:
    await asyncio.to_thread(_delete_cached_sync, kind, commit, version)


def _store_cached_sync(kind: str, commit: str, version: str, payload: dict) -> None:
    if not _enabled() or not commit:
        return
    try:
        with _connection() as conn:
            conn.execute(
                "INSERT INTO llm_cache (kind, version, commit_sha, payload, ts) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (kind, version, commit_sha) "
                "DO UPDATE SET payload = excluded.payload, ts = excluded.ts",
                (kind, version, commit, json.dumps(payload), time.time()),
            )
            conn.execute(
                "DELETE FROM llm_cache WHERE kind = ? AND rowid NOT IN ("
                "SELECT rowid FROM llm_cache WHERE kind = ? "
                "ORDER BY ts DESC, rowid DESC LIMIT ?)",
                (kind, kind, _MAX_ENTRIES),
            )
            conn.commit()
    except (OSError, sqlite3.Error):
        return


async def store_cached(kind: str, commit: str, version: str, payload: dict) -> None:
    await asyncio.to_thread(_store_cached_sync, kind, commit, version, payload)
