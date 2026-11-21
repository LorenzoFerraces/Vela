from __future__ import annotations

from app.core.llm.provider import LlmConfig
from app.core.llm.providers.base import LlmProvider

_JSON_ONLY_TAIL = (
    "\n\nRespond with a single valid JSON object only. No prose, no markdown fences."
)


class OpenAICompatibleProvider(LlmProvider):
    """OpenAI-compatible chat completions wire format."""

    def build_request(self, config: LlmConfig, prompt: str, schema: dict) -> dict:
        """Build a chat completions request body asking for JSON."""
        # ponytail: the schema is Gemini responseSchema-shaped, so chat providers
        # rely on the prompt's field descriptions + the JSON-only tail, not the schema.
        return {
            "model": config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }

    def prepare_prompt(self, prompt: str, config: LlmConfig) -> str:
        """Append the JSON-only instruction to the prompt."""
        return prompt + _JSON_ONLY_TAIL

    def extract_text(self, body: dict) -> str:
        """Return the first choice's message content."""
        text = body["choices"][0]["message"]["content"]
        if not isinstance(text, str):
            raise TypeError("LLM response text must be a string.")
        return text

    def models_url(self, config: LlmConfig) -> str | None:
        """Model listing URL from the base URL, or None when unset."""
        if not config.base_url:
            return None
        return f"{config.base_url}/models"
