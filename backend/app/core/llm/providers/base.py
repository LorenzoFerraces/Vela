"""Provider-agnostic LLM transport shared by all providers."""
from __future__ import annotations

import abc
import json
import logging

import httpx

from app.core.exceptions import LlmCallError
from app.core.llm.provider import LlmConfig
from app.core.security.outbound_url import validate_outbound_url

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

    def _assert_public_url(self, config: LlmConfig) -> None:
        """Re-check host resolution right before each outbound request.

        Guards against DNS rebinding between validation and the actual call.
        """
        try:
            validate_outbound_url(config.url)
        except ValueError as exc:
            raise LlmCallError(
                "Could not complete AI analysis. Try again later."
            ) from exc

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
        self._assert_public_url(config)
        try:
            response = await get_client().post(
                config.url,
                headers=config.headers,
                params=config.params,
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            status_code = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            logger.info(
                "%s analysis request failed: %s",
                config.provider,
                status_code,
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
        self._assert_public_url(config)
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
        if not isinstance(body, dict):
            raise LlmCallError("Could not reach the provider.")
        raw_models = body.get("models")
        if raw_models is None and "data" in body:
            raw_models = body.get("data")
        if not isinstance(raw_models, list):
            raise LlmCallError("Could not reach the provider.")
        names: list[str] = []
        if "models" in body:
            for item in raw_models:
                name = item.get("name") if isinstance(item, dict) else None
                if isinstance(name, str):
                    names.append(name.removeprefix("models/"))
        else:
            for item in raw_models:
                model_id = item.get("id") if isinstance(item, dict) else None
                if isinstance(model_id, str):
                    names.append(model_id)
        return names
