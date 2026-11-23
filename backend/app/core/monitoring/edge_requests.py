from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdgeRequestRates:
    rates_by_host: dict[str, float]
    available: bool


_CACHE_TTL_SECONDS = 5
_cache: tuple[float, EdgeRequestRates] | None = None


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
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_rates(path: Path, window_seconds: int) -> dict[str, float]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    counts: dict[str, int] = defaultdict(int)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                timestamp = _parse_timestamp(entry.get("StartUTC"))
                if timestamp is None or timestamp < cutoff:
                    continue
                host = entry.get("RequestHost") or entry.get("RouterName")
                if isinstance(host, str) and host:
                    counts[host] += 1
    except OSError:
        logger.warning("Cannot read edge access log at %s", path)
        return {}
    return {host: count / window_seconds for host, count in counts.items()}


def get_edge_request_rates(window_seconds: int = 60) -> EdgeRequestRates:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    path = _configured_path()
    if path is None:
        result = EdgeRequestRates(rates_by_host={}, available=False)
    else:
        rates = _read_rates(path, window_seconds)
        result = EdgeRequestRates(rates_by_host=rates, available=True)
    _cache = (now, result)
    return result
