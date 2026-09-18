"""generate_json registry dispatch and user-provider failure mapping."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.exceptions import (
    LlmCallError,
    LlmNotConfiguredError,
    LlmProviderError,
)
from app.core.llm.client import generate_json
from app.core.llm.provider import LlmConfig
from app.core.llm.providers import base

_NO_LLM_VARS = (
    "VELA_VERTEX_API_KEY",
    "VELA_VERTEX_PROJECT_ID",
    "VELA_VERTEX_LOCATION",
    "VELA_VERTEX_MODEL",
    "VELA_GEMINI_API_KEY",
    "VELA_GEMINI_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _NO_LLM_VARS:
        monkeypatch.delenv(name, raising=False)


def _config(origin: str) -> LlmConfig:
    return LlmConfig(
        provider="gemini",
        url="https://generativelanguage.googleapis.com/v1beta/models/m:generateContent",
        headers={},
        params={"key": "k"},
        model="m",
        origin=origin,
    )


class _ErrorClient:
    def __init__(self, error: Exception):
        self.error = error

    async def post(self, url, headers=None, params=None, json=None):
        raise self.error


class _OkClient:
    async def post(self, url, headers=None, params=None, json=None):
        class _Response:
            status_code = 200
            text = "{}"

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "candidates": [
                        {"content": {"parts": [{"text": '{"ok": 1}'}]}}
                    ]
                }

        return _Response()


def _use(monkeypatch: pytest.MonkeyPatch, client: object) -> None:
    monkeypatch.setattr(base, "get_client", lambda: client)


def _http_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.test")
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(401, request=request)
    )


def test_server_origin_error_stays_llm_call_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _ErrorClient(_http_error()))
    with pytest.raises(LlmCallError, match="Could not complete AI analysis"):
        asyncio.run(
            generate_json(prompt="P", schema={}, config=_config("server"))
        )


def test_user_origin_error_becomes_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "env-key")
    _use(monkeypatch, _ErrorClient(_http_error()))
    with pytest.raises(LlmProviderError) as excinfo:
        asyncio.run(generate_json(prompt="P", schema={}, config=_config("user")))
    assert excinfo.value.fallback_available is True


def test_user_origin_error_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _ErrorClient(_http_error()))
    with pytest.raises(LlmProviderError) as excinfo:
        asyncio.run(generate_json(prompt="P", schema={}, config=_config("user")))
    assert excinfo.value.fallback_available is False


def test_unconfigured_raises_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _ErrorClient(_http_error()))
    with pytest.raises(LlmNotConfiguredError, match="not configured"):
        asyncio.run(generate_json(prompt="P", schema={}))


def test_dispatches_to_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _OkClient())
    assert (
        asyncio.run(
            generate_json(prompt="P", schema={}, config=_config("user"))
        )
        == {"ok": 1}
    )
