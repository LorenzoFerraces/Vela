"""In-process sliding-window limiter for unauthenticated endpoints."""

# ponytail: per-process limiter; use a shared store if multiple workers are deployed.

from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_WINDOW_SECONDS = 300.0
_MAX_ATTEMPTS = 10
_buckets: dict[str, deque[float]] = defaultdict(deque)


def client_identity(request: Request) -> str:
    """Prefer a forwarded client only when the peer is an allowed proxy."""
    peer = request.client.host if request.client else "unknown"
    allowed = {
        value.strip()
        for value in os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1").split(",")
        if value.strip()
    }
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded if peer in allowed and forwarded else peer


def check_rate_limit(key: str) -> None:
    # VELA_DISABLE_RATE_LIMIT is test-only; production must keep the limiter on.
    if os.environ.get("VELA_DISABLE_RATE_LIMIT", "").strip() == "1":
        return
    now = time.monotonic()
    bucket = _buckets[key]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
        )
    bucket.append(now)


def reset_for_tests() -> None:
    _buckets.clear()
