from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdgeRequestRates:
    rates_by_host: dict[str, float]
    available: bool


@dataclass
class _CacheState:
    """Byte offset already parsed plus the events still inside the window."""

    offset: int = 0
    events: list[tuple[datetime, str]] = field(default_factory=list)


_CACHE_TTL_SECONDS = 5
_cache: tuple[float, EdgeRequestRates, _CacheState] | None = None


def reset_edge_request_cache() -> None:
    global _cache
    _cache = None


def _configured_path() -> Path | None:
    configured = os.getenv("VELA_EDGE_ACCESS_LOG_PATH", "").strip()
    return Path(configured) if configured else None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _read_rates(
    path: Path, window_seconds: int, state: _CacheState
) -> dict[str, float] | None:
    """Fold newly appended log lines into ``state``; None means unreadable."""
    cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)
    try:
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            offset = state.offset if state.offset <= size else 0
            if offset == 0:
                state.events.clear()
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        logger.warning("Cannot read edge access log at %s", path)
        return None

    # Keep a trailing partial line for the next read so a line being written
    # right now is never half-parsed and skipped.
    last_newline = chunk.rfind(b"\n")
    if last_newline >= 0:
        state.offset = offset + last_newline + 1
        complete = chunk[:last_newline + 1]
    else:
        complete = b""

    for raw_line in complete.split(b"\n"):
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(entry, dict):
            continue
        timestamp = _parse_timestamp(entry.get("StartUTC"))
        if timestamp is None or timestamp < cutoff:
            continue
        host = entry.get("RequestHost") or entry.get("RouterName")
        if isinstance(host, str) and host:
            state.events.append((timestamp, host))

    state.events = [event for event in state.events if event[0] >= cutoff]
    counts: dict[str, int] = defaultdict(int)
    for _timestamp, host in state.events:
        counts[host] += 1
    return {host: count / window_seconds for host, count in counts.items()}


def get_edge_request_rates(window_seconds: int = 60) -> EdgeRequestRates:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    path = _configured_path()
    if path is None:
        state = _CacheState()
        result = EdgeRequestRates(rates_by_host={}, available=False)
    else:
        state = _cache[2] if _cache is not None else _CacheState()
        rates = _read_rates(path, window_seconds, state)
        result = (
            EdgeRequestRates(rates_by_host=rates, available=True)
            if rates is not None
            else EdgeRequestRates(rates_by_host={}, available=False)
        )
    _cache = (now, result, state)
    return result
