from __future__ import annotations

from app.core.exceptions import LlmCallError
from app.core.llm.provider import LlmConfig
from app.core.llm.providers.anthropic import AnthropicProvider
from app.core.llm.providers.base import LlmProvider
from app.core.llm.providers.gemini import GeminiProvider
from app.core.llm.providers.openai_compatible import OpenAICompatibleProvider


def get_provider(config: LlmConfig) -> LlmProvider:
    match config.provider:
        case "gemini" | "vertex":
            return GeminiProvider()
        case "openai_compatible":
            return OpenAICompatibleProvider()
        case "anthropic":
            return AnthropicProvider()
        case _:
            raise LlmCallError(f"Unsupported LLM provider: {config.provider}")
