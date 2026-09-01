"""Commit-keyed LLM result cache, avoids paying for repeat analyses of unchanged repos."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

_MAX_ENTRIES = 500
_CACHE_DIR_ENV = "VELA_LLM_CACHE_DIR"


def _cache_root() -> Path:
    override = os.environ.get(_CACHE_DIR_ENV, "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "data"


def _enabled() -> bool:
    return os.environ.get("VELA_LLM_CACHE", "1").strip() != "0"


def _cache_path(kind: str) -> Path:
    return _cache_root() / f"llm_analysis_{kind}.json"


def load_cached(kind: str, commit: str, version: str) -> dict | None:
    if not _enabled() or not commit:
        return None
    try:
        data = json.loads(_cache_path(kind).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get(f"{version}:{commit}")
    if not isinstance(entry, dict):
        return None
    payload = entry.get("payload")
    return payload if isinstance(payload, dict) else None


def delete_cached(kind: str, commit: str, version: str) -> None:
    if not _enabled() or not commit:
        return
    path = _cache_path(kind)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    key = f"{version}:{commit}"
    if key not in data:
        return
    del data[key]
    path.write_text(json.dumps(data), encoding="utf-8")


# ponytail: single-writer assumption (one API process); swap for SQLite if concurrent writers appear
def store_cached(kind: str, commit: str, version: str, payload: dict) -> None:
    if not _enabled() or not commit:
        return
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    path = _cache_path(kind)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data = {
        key: value
        for key, value in data.items()
        if isinstance(value, dict) and isinstance(value.get("ts"), (int, float))
    }
    data[f"{version}:{commit}"] = {"ts": time.time(), "payload": payload}
    if len(data) > _MAX_ENTRIES:
        for key in sorted(data, key=lambda item: data[item]["ts"])[: len(data) - _MAX_ENTRIES]:
            del data[key]
    path.write_text(json.dumps(data), encoding="utf-8")
