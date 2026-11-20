"""Short-lived, single-use tickets for WebSocket authentication."""

from __future__ import annotations

import secrets
import time
import uuid

_TICKET_TTL_SECONDS = 60.0
_tickets: dict[str, tuple[uuid.UUID, str, str, float]] = {}


def issue_ws_ticket(user_id: uuid.UUID, container_id: str, purpose: str) -> str:
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (user_id, container_id, purpose, time.monotonic() + _TICKET_TTL_SECONDS)
    return ticket


def consume_ws_ticket(ticket: str, container_id: str, purpose: str) -> uuid.UUID | None:
    entry = _tickets.pop(ticket, None)
    if entry is None:
        return None
    user_id, expected_container, expected_purpose, expires_at = entry
    if time.monotonic() > expires_at:
        return None
    if (expected_container, expected_purpose) != (container_id, purpose):
        return None
    return user_id


def reset_for_tests() -> None:
    _tickets.clear()
