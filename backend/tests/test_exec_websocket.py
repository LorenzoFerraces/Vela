import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDisconnect


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
    with anonymous_client.websocket_connect(
        "/api/containers/cid-1/exec/ws"
    ) as websocket:
        with pytest.raises(WebSocketDisconnect) as exc:
            websocket.receive_bytes()
    assert exc.value.code == 1008


def test_exec_ws_rejects_invalid_container(
    api_client: TestClient, auth_token: str
) -> None:
    with api_client.websocket_connect(
        f"/api/containers/nonexistent/exec/ws?access_token={auth_token}"
    ) as websocket:
        with pytest.raises(WebSocketDisconnect) as exc:
            websocket.receive_bytes()
    assert exc.value.code == 1008
