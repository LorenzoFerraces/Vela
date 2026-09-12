"""Provider wire formats, shared transport, and registry dispatch."""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.exceptions import LlmCallError
from app.core.llm.provider import LlmConfig
from app.core.llm.providers import base
from app.core.llm.providers.anthropic import AnthropicProvider
from app.core.llm.providers.gemini import GeminiProvider
from app.core.llm.providers.openai_compatible import OpenAICompatibleProvider
from app.core.llm.registry import get_provider

GEMINI_BODY = {
    "candidates": [{"content": {"parts": [{"text": '{"ok": 1}'}]}}]
}


def _gemini_config() -> LlmConfig:
    return LlmConfig(
        provider="gemini",
        url="https://generativelanguage.googleapis.com/v1beta/models/m:generateContent",
        headers={},
        params={"key": "k"},
        model="m",
        origin="user",
    )


def _openai_config() -> LlmConfig:
    return LlmConfig(
        provider="openai_compatible",
        url="https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer sk"},
        params={},
        model="gpt-4o-mini",
        origin="user",
        base_url="https://api.openai.com/v1",
    )


def _anthropic_config() -> LlmConfig:
    return LlmConfig(
        provider="anthropic",
        url="https://api.anthropic.com/v1/messages",
        headers={"x-api-key": "sk", "anthropic-version": "2023-06-01"},
        params={},
        model="claude-sonnet-4-5",
        origin="user",
    )


class _FakeResponse:
    def __init__(self, payload: dict | None, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://provider.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse | Exception):
        self.response = response
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    async def post(self, url, headers=None, params=None, json=None):
        self.posts.append(
            {"url": url, "headers": headers, "params": params, "json": json}
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def get(self, url, headers=None, params=None):
        self.gets.append({"url": url, "headers": headers, "params": params})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _use(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    monkeypatch.setattr(base, "get_client", lambda: client)


def test_gemini_wire_format_matches_current_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_FakeResponse(GEMINI_BODY))
    _use(monkeypatch, client)
    import asyncio

    parsed = asyncio.run(GeminiProvider().generate_json(
        _gemini_config(), prompt="P", schema={"type": "OBJECT"}
    ))
    assert parsed == {"ok": 1}
    posted = client.posts[0]
    assert posted["json"] == {
        "contents": [{"role": "user", "parts": [{"text": "P"}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {"type": "OBJECT"},
        },
    }


def test_openai_wire_format(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"choices": [{"message": {"content": '{"ok": 2}'}}]}
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    parsed = asyncio.run(OpenAICompatibleProvider().generate_json(
        _openai_config(), prompt="P", schema={}
    ))
    assert parsed == {"ok": 2}
    posted = client.posts[0]
    assert posted["json"]["model"] == "gpt-4o-mini"
    assert posted["json"]["response_format"] == {"type": "json_object"}
    assert posted["json"]["messages"] == [{"role": "user", "content": posted["json"]["messages"][0]["content"]}][:1]
    assert "JSON" in posted["json"]["messages"][0]["content"]


def test_anthropic_wire_format_and_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {
        "content": [
            {"type": "text", "text": '```json\n{"ok": 3}\n```'},
        ]
    }
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    parsed = asyncio.run(AnthropicProvider().generate_json(
        _anthropic_config(), prompt="P", schema={}
    ))
    assert parsed == {"ok": 3}
    posted = client.posts[0]
    assert posted["json"]["max_tokens"] == 8192
    assert posted["json"]["messages"] == [{"role": "user", "content": posted["json"]["messages"][0]["content"]}]
    assert posted["url"] == "https://api.anthropic.com/v1/messages"


def test_http_error_raises_llm_call_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = httpx.HTTPStatusError(
        "boom",
        request=httpx.Request("POST", "https://x"),
        response=httpx.Response(401, request=httpx.Request("POST", "https://x")),
    )
    client = _FakeClient(error)
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="Could not complete AI analysis"):
        asyncio.run(GeminiProvider().generate_json(_gemini_config(), prompt="P", schema={}))


def test_malformed_body_raises_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_FakeResponse({"candidates": []}))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="invalid response"):
        asyncio.run(GeminiProvider().generate_json(_gemini_config(), prompt="P", schema={}))


def test_non_dict_json_raises_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"candidates": [{"content": {"parts": [{"text": "42"}]}}]}
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="invalid response"):
        asyncio.run(GeminiProvider().generate_json(_gemini_config(), prompt="P", schema={}))


def test_verify_parses_gemini_model_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"models": [{"name": "models/gemini-a"}, {"name": "gemini-b"}]}
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    names = asyncio.run(GeminiProvider().verify(_gemini_config()))
    assert names == ["gemini-a", "gemini-b"]
    assert client.gets[0]["params"] == {"key": "k"}


def test_verify_parses_openai_model_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    names = asyncio.run(OpenAICompatibleProvider().verify(_openai_config()))
    assert names == ["gpt-4o", "gpt-4o-mini"]
    assert client.gets[0]["url"] == "https://api.openai.com/v1/models"


def test_verify_connection_error_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(httpx.ConnectError("down"))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="Could not reach the provider"):
        asyncio.run(GeminiProvider().verify(_gemini_config()))


def test_anthropic_verify_posts_one_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_FakeResponse({"content": [{"type": "text", "text": "x"}]}))
    _use(monkeypatch, client)
    import asyncio

    assert asyncio.run(AnthropicProvider().verify(_anthropic_config())) is None
    assert client.posts[0]["json"]["max_tokens"] == 1


def test_registry_dispatches() -> None:
    assert isinstance(get_provider(_gemini_config()), GeminiProvider)
    vertex = _gemini_config()
    assert isinstance(
        get_provider(LlmConfig(
            provider="vertex", url=vertex.url, headers=vertex.headers,
            params={}, model=vertex.model,
        )),
        GeminiProvider,
    )
    assert isinstance(get_provider(_openai_config()), OpenAICompatibleProvider)
    assert isinstance(get_provider(_anthropic_config()), AnthropicProvider)
    unknown = LlmConfig(
        provider="mystery", url="u", headers={}, params={}, model="m"
    )
    with pytest.raises(LlmCallError, match="Unsupported LLM provider"):
        get_provider(unknown)
