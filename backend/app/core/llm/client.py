from __future__ import annotations

import json
import logging

import httpx

from app.core.exceptions import LlmCallError, LlmNotConfiguredError
from app.core.llm.provider import resolve_llm_config

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=60.0)
    return _client


async def generate_json(*, prompt: str, schema: dict) -> dict:
    config = resolve_llm_config()
    if config is None:
        raise LlmNotConfiguredError("AI analysis is not configured on this server.")

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    try:
        response = await _get_client().post(
            config.url,
            headers=config.headers,
            params=config.params,
            json=payload,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        response_detail = ""
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            response_detail = exc.response.text[:240]
        logger.info(
            "%s analysis request failed: %s %s",
            config.provider,
            exc,
            response_detail,
        )
        raise LlmCallError("Could not complete AI analysis. Try again later.") from exc

    try:
        body = response.json()
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        if not isinstance(text, str):
            raise TypeError("LLM response text must be a string.")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.info(
            "%s analysis response parse failed: %s",
            config.provider,
            exc,
        )
        raise LlmCallError(
            "AI analysis returned an invalid response. Try again later."
        ) from exc

    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise TypeError("LLM JSON root must be an object.")
        return parsed
    except (TypeError, ValueError) as exc:
        logger.info(
            "%s analysis response parse failed: %s",
            config.provider,
            exc,
        )
        raise LlmCallError(
            "AI analysis returned an invalid response. Try again later."
        ) from exc
