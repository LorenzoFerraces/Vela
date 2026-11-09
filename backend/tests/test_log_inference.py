from __future__ import annotations

from app.core.logging.inference import infer_log_level
from app.db.models import LogLevel


def test_infers_error() -> None:
    assert infer_log_level("ERROR: connection refused") == LogLevel.ERROR
    assert infer_log_level("error: disk full") == LogLevel.ERROR
    assert infer_log_level("Traceback (most recent call last)") == LogLevel.ERROR
    assert infer_log_level("FATAL: password authentication failed") == LogLevel.ERROR


def test_infers_warn() -> None:
    assert infer_log_level("WARNING: deprecated API") == LogLevel.WARN
    assert infer_log_level("warn: retrying in 5s") == LogLevel.WARN


def test_infers_debug() -> None:
    assert infer_log_level("DEBUG: processing request") == LogLevel.DEBUG
    assert infer_log_level("debug: cache miss for key=abc") == LogLevel.DEBUG


def test_defaults_to_info() -> None:
    assert infer_log_level("Server started on port 8080") == LogLevel.INFO
    assert infer_log_level("GET /api/health 200") == LogLevel.INFO
