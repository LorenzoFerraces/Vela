"""Tests for stream_exec stdin writes running off the event loop."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.core.containers.docker_orchestrator import DockerOrchestrator


class _FakeExecRuntime:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.writes: list[bytes] = []

    def read(self, size: int) -> bytes:
        time.sleep(0.05)
        return b""

    def write(self, data: bytes) -> int:
        time.sleep(0.2)
        with self._lock:
            self.writes.append(data)
        return len(data)

    def close(self) -> None:
        pass


async def test_stream_exec_write_callable_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _FakeExecRuntime()
    orch = DockerOrchestrator.__new__(DockerOrchestrator)

    def fake_session(container_id: str, cols: int, rows: int) -> tuple[str, object]:
        return "exec-1", runtime

    monkeypatch.setattr(orch, "_create_exec_session", fake_session)

    _, stdin_write, close_fn, exec_id = await orch.stream_exec("cid-1")
    assert exec_id == "exec-1"

    start = time.monotonic()
    stdin_write(b"first\n")
    stdin_write(b"second\n")
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"write callable blocked the event loop for {elapsed:.3f}s"

    deadline = time.monotonic() + 5
    while len(runtime.writes) < 2 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert runtime.writes == [b"first\n", b"second\n"]

    close_fn()
