from __future__ import annotations

from app.core.llm.provider import GEMINI_API_ROOT, LlmConfig
from app.core.llm.providers.base import LlmProvider


class GeminiProvider(LlmProvider):
    def build_request(self, config: LlmConfig, prompt: str, schema: dict) -> dict:
        return {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }

    def extract_text(self, body: dict) -> str:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        if not isinstance(text, str):
            raise TypeError("LLM response text must be a string.")
        return text

    def models_url(self, config: LlmConfig) -> str | None:
        # The key travels in config.params for both server and user configs.
        return f"{GEMINI_API_ROOT}/models"
