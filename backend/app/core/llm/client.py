from __future__ import annotations

from app.core.exceptions import (
    LlmCallError,
    LlmNotConfiguredError,
    LlmProviderError,
)
from app.core.llm.provider import LlmConfig, resolve_llm_config
from app.core.llm.registry import get_provider


async def generate_json(
    *,
    prompt: str,
    schema: dict,
    config: LlmConfig | None = None,
) -> dict:
    resolved = config if config is not None else resolve_llm_config()
    if resolved is None:
        raise LlmNotConfiguredError("AI analysis is not configured on this server.")
    try:
        return await get_provider(resolved).generate_json(
            resolved, prompt=prompt, schema=schema
        )
    except LlmCallError as exc:
        if resolved.origin == "user":
            raise LlmProviderError(
                str(exc), fallback_available=resolve_llm_config() is not None
            ) from exc
        raise
