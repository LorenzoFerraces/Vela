from __future__ import annotations

import re

from app.db.models import LogLevel

_ERROR_RE = re.compile(
    r"\b(ERROR|FATAL|CRITICAL|Exception|Traceback|panic)\b",
    re.IGNORECASE,
)
_WARN_RE = re.compile(r"\b(WARN|WARNING)\b", re.IGNORECASE)
_DEBUG_RE = re.compile(r"\b(DEBUG|TRACE)\b", re.IGNORECASE)


def infer_log_level(message: str) -> LogLevel:
    if _ERROR_RE.search(message):
        return LogLevel.ERROR
    if _WARN_RE.search(message):
        return LogLevel.WARN
    if _DEBUG_RE.search(message):
        return LogLevel.DEBUG
    return LogLevel.INFO
