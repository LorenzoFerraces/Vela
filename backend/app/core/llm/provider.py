from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_LLM_MODEL = "gemini-3.5-flash-lite"

GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    url: str
    headers: dict[str, str]
    params: dict[str, str]
    model: str
    origin: str = "server"
    base_url: str | None = None


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def resolve_llm_config() -> LlmConfig | None:
    vertex_api_key = _env("VELA_VERTEX_API_KEY")
    vertex_project_id = _env("VELA_VERTEX_PROJECT_ID")
    if vertex_api_key and vertex_project_id:
        location = _env("VELA_VERTEX_LOCATION") or "us-central1"
        model = _env("VELA_VERTEX_MODEL") or DEFAULT_LLM_MODEL
        return LlmConfig(
            provider="vertex",
            url=(
                f"https://{location}-aiplatform.googleapis.com/v1/projects/"
                f"{vertex_project_id}/locations/{location}/publishers/google/"
                f"models/{model}:generateContent"
            ),
            headers={"x-goog-api-key": vertex_api_key},
            params={},
            model=model,
        )

    gemini_api_key = _env("VELA_GEMINI_API_KEY")
    if gemini_api_key:
        model = _env("VELA_GEMINI_MODEL") or DEFAULT_LLM_MODEL
        return LlmConfig(
            provider="gemini",
            url=f"{GEMINI_API_ROOT}/models/{model}:generateContent",
            headers={},
            params={"key": gemini_api_key},
            model=model,
        )

    return None
