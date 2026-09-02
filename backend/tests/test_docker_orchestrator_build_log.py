"""Tests for the bounded build-log tail used by DockerOrchestrator.build_image."""

from __future__ import annotations

from app.core.containers.docker_orchestrator import (
    _MAX_BUILD_LOG_BYTES,
    _BuildLogTail,
)


def test_build_log_tail_keeps_trailing_content_within_budget() -> None:
    tail = _BuildLogTail()
    chunk = "x" * (_MAX_BUILD_LOG_BYTES // 2)
    for _ in range(4):
        tail.append(chunk)
    assert tail.size <= _MAX_BUILD_LOG_BYTES
    assert tail.text() == chunk * 2


def test_build_log_tail_keeps_single_oversized_item_whole() -> None:
    tail = _BuildLogTail()
    oversized = "y" * (_MAX_BUILD_LOG_BYTES * 2)
    tail.append("seed")
    tail.append(oversized)
    assert tail.text() == oversized
    assert tail.size > _MAX_BUILD_LOG_BYTES
