"""Regression tests for interactive exec over Docker's raw socket."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

from app.core.containers.docker_orchestrator import DockerOrchestrator


async def test_stream_exec_writes_to_read_only_socket(monkeypatch: Any) -> None:
    """docker's ``exec_start(socket=True)`` returns a read-only SocketIO.

    Writing through it raises ``io.UnsupportedOperation``; input must fall back
    to the underlying socket or keystrokes never reach the shell. Output must
    likewise flow back through the returned stream.
    """
    ours, theirs = socket.socketpair()
    read_only = socket.SocketIO(ours, "rb")
    orchestrator = DockerOrchestrator(client=object())
    monkeypatch.setattr(
        orchestrator, "_create_exec_session", lambda *args, **kwargs: ("exec-1", read_only)
    )

    stream, write, close, exec_id = await orchestrator.stream_exec("container-1")
    assert exec_id == "exec-1"
    try:
        write(b"echo hi\n")
        theirs.settimeout(2.0)
        assert theirs.recv(1024) == b"echo hi\n"

        theirs.sendall(b"container output\n")
        chunk = await asyncio.wait_for(anext(stream), timeout=5.0)
        assert b"container output" in chunk
    finally:
        close()
        theirs.close()
