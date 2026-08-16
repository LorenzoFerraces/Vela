import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDisconnect

from app.api.routes import containers as containers_routes


def test_exec_ws_connects_and_receives_prompt(
    api_client: TestClient, auth_token: str
) -> None:
    with api_client.websocket_connect(
        f"/api/containers/cid-1/exec/ws?access_token={auth_token}"
    ) as websocket:
        data = websocket.receive_bytes()
    assert b"root@" in data
    assert b":~# " in data


def test_exec_ws_sends_input_and_gets_echo(
    api_client: TestClient, auth_token: str
) -> None:
    with api_client.websocket_connect(
        f"/api/containers/cid-1/exec/ws?access_token={auth_token}"
    ) as websocket:
        websocket.receive_bytes()
        websocket.send_text("hello\n")
        time.sleep(0.3)
        data = websocket.receive_bytes()
    assert b"hello" in data


def test_exec_ws_rejects_unauthenticated(
    anonymous_client: TestClient
) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with anonymous_client.websocket_connect(
            "/api/containers/cid-1/exec/ws"
        ):
            pass
    assert exc.value.code == 1008


def test_exec_ws_rejects_invalid_token(
    api_client: TestClient
) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with api_client.websocket_connect(
            "/api/containers/cid-1/exec/ws?access_token=not-a-jwt"
        ):
            pass
    assert exc.value.code == 1008


def test_exec_ws_rejects_invalid_container(
    api_client: TestClient, auth_token: str
) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with api_client.websocket_connect(
            f"/api/containers/nonexistent/exec/ws?access_token={auth_token}"
        ):
            pass
    assert exc.value.code == 1008


def test_exec_ws_semaphore_timeout_rejects(
    make_authed_client, auth_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(containers_routes, "_exec_semaphore", asyncio.Semaphore(0))
    monkeypatch.setattr(
        containers_routes, "_EXEC_SEMAPHORE_ACQUIRE_TIMEOUT", 0.1
    )
    with make_authed_client() as client:
        with client.websocket_connect(
            f"/api/containers/cid-1/exec/ws?access_token={auth_token}"
        ) as websocket:
            with pytest.raises(WebSocketDisconnect) as exc:
                websocket.receive_text()
    assert exc.value.code == 1013


def test_exec_ws_surfaces_start_failure(
    make_authed_client, fake_orchestrator, auth_token: str
) -> None:
    def broken_stream_exec(*args: object, **kwargs: object) -> object:
        raise RuntimeError("OCI runtime exec failed: sh not found")

    fake_orchestrator.stream_exec = broken_stream_exec
    with make_authed_client() as client:
        with client.websocket_connect(
            f"/api/containers/cid-1/exec/ws?access_token={auth_token}"
        ) as websocket:
            websocket.send_text(json.dumps({"cols": 80, "rows": 24}))
            message = websocket.receive_text()
            with pytest.raises(WebSocketDisconnect) as exc:
                websocket.receive_text()
    assert "Could not start a shell" in message
    assert exc.value.code == 1011


def test_exec_ws_session_max_lifetime(
    make_authed_client, auth_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_EXEC_MAX_SESSION_SECONDS", "1")
    with make_authed_client() as client:
        with client.websocket_connect(
            f"/api/containers/cid-1/exec/ws?access_token={auth_token}"
        ) as websocket:
            websocket.send_text(json.dumps({"cols": 80, "rows": 24}))
            texts: list[str] = []
            close_code: int | None = None
            for _ in range(100):
                message = websocket.receive()
                if message["type"] == "websocket.close":
                    close_code = message.get("code")
                    break
                if "text" in message:
                    texts.append(message["text"])
    assert "[session expired]" in texts
    assert close_code == 1000


def test_exec_ws_strict_resize_validation() -> None:
    from app.api.routes.containers import _parse_resize_message

    assert (
        _parse_resize_message('{"resize": {"cols": 120, "rows": 40}}')
        == (120, 40)
    )
    assert (
        _parse_resize_message('{"resize": {"cols": 120, "rows": 40}, "x": 1}')
        is None
    )
    assert _parse_resize_message('{"resize": {"cols": 0, "rows": 40}}') is None
    assert _parse_resize_message('{"resize": {"cols": 501, "rows": 40}}') is None
    assert _parse_resize_message('{"resize": {"cols": 80, "rows": 501}}') is None
    assert _parse_resize_message('{"resize": {"cols": "80", "rows": 24}}') is None
    assert _parse_resize_message('{"resize": {"cols": true, "rows": 24}}') is None
    assert _parse_resize_message('{"resize": {"cols": 80}}') is None
    assert _parse_resize_message('{"resize": "80"}') is None
    assert _parse_resize_message('{"cols": 80, "rows": 24}') is None
    assert _parse_resize_message("[1, 2]") is None
    assert _parse_resize_message("not json") is None


def test_exec_ws_invalid_resize_forwarded_to_stdin(
    api_client: TestClient, auth_token: str
) -> None:
    with api_client.websocket_connect(
        f"/api/containers/cid-1/exec/ws?access_token={auth_token}"
    ) as websocket:
        websocket.receive_bytes()
        websocket.send_text('{"resize": {"cols": 99999, "rows": 24}}')
        websocket.send_text("\n")
        data = b""
        for _ in range(20):
            data += websocket.receive_bytes()
            if b"99999" in data or data.endswith(b":~# "):
                break
    assert b"99999" in data


def test_exec_ws_valid_resize_swallowed(
    api_client: TestClient, auth_token: str
) -> None:
    with api_client.websocket_connect(
        f"/api/containers/cid-1/exec/ws?access_token={auth_token}"
    ) as websocket:
        websocket.receive_bytes()
        websocket.send_text(json.dumps({"resize": {"cols": 100, "rows": 30}}))
        websocket.send_text("probe\n")
        data = b""
        for _ in range(20):
            data += websocket.receive_bytes()
            if b"probe" in data:
                break
    assert b"probe" in data
    assert b"resize" not in data
