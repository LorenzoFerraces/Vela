"""Unit tests for LLM provider resolution."""

from __future__ import annotations

import pytest

from app.core.llm.provider import DEFAULT_LLM_MODEL, resolve_llm_config

_LLM_ENV_VARS = (
    "VELA_VERTEX_API_KEY",
    "VELA_VERTEX_PROJECT_ID",
    "VELA_VERTEX_LOCATION",
    "VELA_VERTEX_MODEL",
    "VELA_GEMINI_API_KEY",
    "VELA_GEMINI_MODEL",
)


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all server LLM env vars so resolution starts unconfigured."""
    for name in _LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_vertex_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vertex key plus project resolve a vertex config with the api-key header."""
    monkeypatch.setenv("VELA_VERTEX_API_KEY", "vertex-key")
    monkeypatch.setenv("VELA_VERTEX_PROJECT_ID", "project")
    config = resolve_llm_config()
    assert config is not None
    assert config.provider == "vertex"
    assert config.headers == {"x-goog-api-key": "vertex-key"}
    assert config.params == {}
    assert "locations/us-central1" in config.url
    assert f"{DEFAULT_LLM_MODEL}:generateContent" in config.url


def test_vertex_overrides_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """Location and model env vars override the Vertex URL and model defaults."""
    monkeypatch.setenv("VELA_VERTEX_API_KEY", "key")
    monkeypatch.setenv("VELA_VERTEX_PROJECT_ID", "project")
    monkeypatch.setenv("VELA_VERTEX_LOCATION", "europe-west1")
    monkeypatch.setenv("VELA_VERTEX_MODEL", "gemini-2.5-pro")
    config = resolve_llm_config()
    assert config is not None
    assert "europe-west1-aiplatform.googleapis.com" in config.url
    assert config.model == "gemini-2.5-pro"


def test_gemini_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Gemini key alone resolves a gemini config with the key as a query param."""
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "gemini-key")
    config = resolve_llm_config()
    assert config is not None
    assert config.provider == "gemini"
    assert config.params == {"key": "gemini-key"}
    assert config.headers == {}
    assert f"{DEFAULT_LLM_MODEL}:generateContent" in config.url


def test_incomplete_vertex_config_falls_back_to_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vertex without a project ID falls back to the gemini provider."""
    monkeypatch.setenv("VELA_VERTEX_API_KEY", "vertex-key")
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "gemini-key")
    config = resolve_llm_config()
    assert config is not None
    assert config.provider == "gemini"


def test_no_provider() -> None:
    """With no env vars configured, resolution returns no config."""
    assert resolve_llm_config() is None
