"""Provider-agnostic LLM transport shared by all providers."""
from __future__ import annotations

import abc
import json
import logging

import httpx

from app.core.exceptions import LlmCallError
from app.core.llm.provider import LlmConfig

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=60.0)
    return _client


class LlmProvider(abc.ABC):
    """One wire format of LLM API."""

    @abc.abstractmethod
    def build_request(self, config: LlmConfig, prompt: str, schema: dict) -> dict:
        """JSON body for a generate request."""

    @abc.abstractmethod
    def extract_text(self, body: dict) -> str:
        """Raw model text from a generate response body."""

    def prepare_prompt(self, prompt: str, config: LlmConfig) -> str:
        return prompt

    def parse_json_text(self, text: str) -> dict:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON root must be an object.")
        return parsed

    def models_url(self, config: LlmConfig) -> str | None:
        return None

    async def generate_json(
        self, config: LlmConfig, *, prompt: str, schema: dict
    ) -> dict:
        payload = self.build_request(
            config, self.prepare_prompt(prompt, config), schema
        )
        try:
            response = await get_client().post(
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
            raise LlmCallError(
                "Could not complete AI analysis. Try again later."
            ) from exc
        try:
            body = response.json()
            return self.parse_json_text(self.extract_text(body))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.info(
                "%s analysis response parse failed: %s",
                config.provider,
                exc,
            )
            raise LlmCallError(
                "AI analysis returned an invalid response. Try again later."
            ) from exc

    async def verify(self, config: LlmConfig) -> list[str] | None:
        url = self.models_url(config)
        if url is None:
            return None
        try:
            response = await get_client().get(
                url, headers=config.headers, params=config.params
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LlmCallError("Could not reach the provider.") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise LlmCallError("Could not reach the provider.") from exc
        names: list[str] = []
        if isinstance(body, dict):
            raw_models = body.get("models")
            if isinstance(raw_models, list):
                for item in raw_models:
                    name = item.get("name") if isinstance(item, dict) else None
                    if isinstance(name, str):
                        names.append(name.removeprefix("models/"))
            else:
                raw_data = body.get("data")
                if isinstance(raw_data, list):
                    for item in raw_data:
                        model_id = item.get("id") if isinstance(item, dict) else None
                        if isinstance(model_id, str):
                            names.append(model_id)
        return names
