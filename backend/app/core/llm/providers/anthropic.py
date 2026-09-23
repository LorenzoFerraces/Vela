from __future__ import annotations

import httpx

from app.core.exceptions import LlmCallError
from app.core.llm.provider import LlmConfig
from app.core.llm.providers import base
from app.core.llm.providers.base import LlmProvider

_JSON_ONLY_TAIL = (
    "\n\nRespond with a single valid JSON object only. No prose, no markdown fences."
)


class AnthropicProvider(LlmProvider):
    def build_request(self, config: LlmConfig, prompt: str, schema: dict) -> dict:
        return {
            "model": config.model,
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": prompt}],
        }

    def prepare_prompt(self, prompt: str, config: LlmConfig) -> str:
        return prompt + _JSON_ONLY_TAIL

    def extract_text(self, body: dict) -> str:
        blocks = body.get("content")
        if not isinstance(blocks, list):
            raise TypeError("Anthropic response content must be a list.")
        return "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )

    def parse_json_text(self, text: str) -> dict:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        return super().parse_json_text(stripped)

    async def verify(self, config: LlmConfig) -> None:
        # No model-listing endpoint; a 1-token completion proves the key works.
        self._assert_public_url(config)
        try:
            response = await base.get_client().post(
                config.url,
                headers=config.headers,
                json={
                    "model": config.model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LlmCallError("Could not reach the provider.") from exc
        return None
