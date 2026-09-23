"""Per-user LLM provider settings routes."""
from __future__ import annotations

import httpx
import pytest

from app.api.routes import settings as settings_routes
from app.core.exceptions import LlmCallError

_LLM_VARS = (
    "VELA_VERTEX_API_KEY",
    "VELA_VERTEX_PROJECT_ID",
    "VELA_VERTEX_LOCATION",
    "VELA_VERTEX_MODEL",
    "VELA_GEMINI_API_KEY",
    "VELA_GEMINI_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _LLM_VARS:
        monkeypatch.delenv(name, raising=False)


class _StubProvider:
    def __init__(
        self, models: list[str] | None = None, error: Exception | None = None
    ) -> None:
        self.models = models
        self.error = error

    async def verify(self, config: object) -> list[str] | None:
        if self.error is not None:
            raise self.error
        return self.models


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: _StubProvider) -> None:
    monkeypatch.setattr(settings_routes, "get_provider", lambda config: provider)


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://provider.test/models")
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(status_code, request=request)
    )


def test_get_llm_provider_empty(api_client) -> None:
    api_client.delete("/api/settings/llm-provider")
    response = api_client.get("/api/settings/llm-provider")
    assert response.status_code == 200
    assert response.json() is None


def test_put_and_get_llm_provider_roundtrip(api_client) -> None:
    response = api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "gemini-2.5-flash", "api_key": "sk-test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "provider": "gemini",
        "base_url": None,
        "model": "gemini-2.5-flash",
        "has_key": True,
    }
    again = api_client.get("/api/settings/llm-provider")
    assert again.status_code == 200
    assert again.json() == body


def test_put_llm_provider_without_key_when_absent_returns_400(api_client) -> None:
    api_client.delete("/api/settings/llm-provider")
    response = api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "gemini-2.5-flash"},
    )
    assert response.status_code == 400
    assert "API key required" in response.json()["detail"]


def test_put_llm_provider_blank_key_keeps_existing(api_client) -> None:
    api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "old-model", "api_key": "sk-old"},
    )
    response = api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "new-model"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "new-model"
    assert body["has_key"] is True


def test_put_openai_compatible_requires_base_url(api_client) -> None:
    response = api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "openai_compatible", "model": "gpt-4o-mini", "api_key": "k"},
    )
    assert response.status_code == 422


def test_put_openai_compatible_stores_base_url(api_client) -> None:
    response = api_client.put(
        "/api/settings/llm-provider",
        json={
            "provider": "openai_compatible",
            "base_url": "https://openrouter.ai/api/v1/",
            "model": "gpt-4o-mini",
            "api_key": "k",
        },
    )
    assert response.status_code == 200
    assert response.json()["base_url"] == "https://openrouter.ai/api/v1"


def test_put_non_openai_drops_base_url(api_client) -> None:
    response = api_client.put(
        "/api/settings/llm-provider",
        json={
            "provider": "anthropic",
            "base_url": "https://ignored.example/v1",
            "model": "claude-sonnet-4-5",
            "api_key": "k",
        },
    )
    assert response.status_code == 200
    assert response.json()["base_url"] is None


def test_delete_llm_provider(api_client) -> None:
    api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    response = api_client.delete("/api/settings/llm-provider")
    assert response.status_code == 204
    assert api_client.get("/api/settings/llm-provider").json() is None


def test_test_llm_provider_success(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_provider(monkeypatch, _StubProvider(models=["m1", "m2"]))
    response = api_client.post(
        "/api/settings/llm-provider/test",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "models": ["m1", "m2"]}


def test_test_llm_provider_invalid_key_returns_400(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = LlmCallError("Could not reach the provider.")
    error.__cause__ = _status_error(401)
    _use_provider(monkeypatch, _StubProvider(error=error))
    response = api_client.post(
        "/api/settings/llm-provider/test",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid API key."


def test_test_llm_provider_rejected_returns_400(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = LlmCallError("Could not reach the provider.")
    error.__cause__ = _status_error(400)
    _use_provider(monkeypatch, _StubProvider(error=error))
    response = api_client.post(
        "/api/settings/llm-provider/test",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "The provider rejected the request."


def test_test_llm_provider_unreachable_returns_400(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = LlmCallError("Could not reach the provider.")
    error.__cause__ = httpx.ConnectError("no route")
    _use_provider(monkeypatch, _StubProvider(error=error))
    response = api_client.post(
        "/api/settings/llm-provider/test",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Endpoint unreachable. Check the base URL and API key."
    )


def test_gemini_status_reports_user_provider(api_client) -> None:
    api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "anthropic", "model": "claude-sonnet-4-5", "api_key": "k"},
    )
    response = api_client.get("/api/settings/gemini-status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["user_provider"]["provider"] == "anthropic"
    assert body["user_provider"]["has_key"] is True


def test_gemini_status_unconfigured(api_client) -> None:
    api_client.delete("/api/settings/llm-provider")
    response = api_client.get("/api/settings/gemini-status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["user_provider"] is None
