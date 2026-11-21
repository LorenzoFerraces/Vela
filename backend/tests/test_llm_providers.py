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
    """Build a user-origin Gemini config for provider tests."""
    return LlmConfig(
        provider="gemini",
        url="https://generativelanguage.googleapis.com/v1beta/models/m:generateContent",
        headers={},
        params={"key": "k"},
        model="m",
        origin="user",
    )


def _openai_config() -> LlmConfig:
    """Build a user-origin OpenAI-compatible config for provider tests."""
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
    """Build a user-origin Anthropic config for provider tests."""
    return LlmConfig(
        provider="anthropic",
        url="https://api.anthropic.com/v1/messages",
        headers={"x-api-key": "sk", "anthropic-version": "2023-06-01"},
        params={},
        model="claude-sonnet-4-5",
        origin="user",
    )


class _FakeResponse:
    """Stand-in for an httpx response with a preset payload and status code."""

    def __init__(self, payload: object | None, status_code: int = 200):
        """Store the payload to serve and the status code to report."""
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else ""

    def raise_for_status(self) -> None:
        """Raise httpx.HTTPStatusError when the stored status is an error."""
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://provider.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> object:
        """Return the stored payload, raising ValueError when there is none."""
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    """Async HTTP client stand-in that records requests and replays one response."""

    def __init__(self, response: _FakeResponse | Exception):
        """Store the response to return, or the exception every call raises."""
        self.response = response
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    async def post(self, url, headers=None, params=None, json=None):
        """Record the request and return the canned response or raise the error."""
        self.posts.append(
            {"url": url, "headers": headers, "params": params, "json": json}
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def get(self, url, headers=None, params=None):
        """Record the request and return the canned response or raise the error."""
        self.gets.append({"url": url, "headers": headers, "params": params})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _use(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    """Patch the provider base module to hand out the fake client."""
    monkeypatch.setattr(base, "get_client", lambda: client)


def test_gemini_wire_format_matches_current_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini posts contents plus responseMimeType/schema and parses the text part."""
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
    """OpenAI-compatible posts chat completions with the json_object response format."""
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
    """Anthropic posts max_tokens and messages and parses a fenced json block."""
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
    """An HTTP status error from the transport surfaces as LlmCallError."""
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
    """A Gemini body without candidates raises an invalid-response LlmCallError."""
    client = _FakeClient(_FakeResponse({"candidates": []}))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="invalid response"):
        asyncio.run(GeminiProvider().generate_json(_gemini_config(), prompt="P", schema={}))


def test_non_dict_json_raises_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model text that parses to a non-dict raises an invalid-response error."""
    body = {"candidates": [{"content": {"parts": [{"text": "42"}]}}]}
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="invalid response"):
        asyncio.run(GeminiProvider().generate_json(_gemini_config(), prompt="P", schema={}))


def test_verify_parses_gemini_model_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini verify strips the models/ prefix and passes the key as a param."""
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
    """OpenAI verify reads ids from GET {base_url}/models."""
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
    """A connection error during verify raises LlmCallError."""
    client = _FakeClient(httpx.ConnectError("down"))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="Could not reach the provider"):
        asyncio.run(GeminiProvider().verify(_gemini_config()))


def test_anthropic_verify_posts_one_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic verify has no model list and posts a one-token ping."""
    client = _FakeClient(_FakeResponse({"content": [{"type": "text", "text": "x"}]}))
    _use(monkeypatch, client)
    import asyncio

    assert asyncio.run(AnthropicProvider().verify(_anthropic_config())) is None
    assert client.posts[0]["json"]["max_tokens"] == 1


def test_verify_empty_model_list_is_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty model list counts as a successful verify."""
    client = _FakeClient(_FakeResponse({"models": []}))
    _use(monkeypatch, client)
    import asyncio

    assert asyncio.run(GeminiProvider().verify(_gemini_config())) == []


def test_verify_non_dict_body_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-dict JSON body during verify raises LlmCallError."""
    client = _FakeClient(_FakeResponse(["not", "a", "dict"]))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="Could not reach the provider"):
        asyncio.run(GeminiProvider().verify(_gemini_config()))


def test_verify_error_envelope_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error envelope in the verify response raises LlmCallError."""
    client = _FakeClient(_FakeResponse({"error": {"code": 403}}))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="Could not reach the provider"):
        asyncio.run(GeminiProvider().verify(_gemini_config()))


def test_registry_dispatches() -> None:
    """The registry maps each provider name to its implementation and rejects unknowns."""
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
