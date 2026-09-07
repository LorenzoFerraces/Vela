"""Per-user LLM provider storage and resolution."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LlmProviderConfigError
from app.core.llm.provider import GEMINI_API_ROOT, LlmConfig, resolve_llm_config
from app.core.security.secrets import decrypt_secret, encrypt_secret
from app.db.models import UserLlmProvider

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-5"
ANTHROPIC_API_ROOT = "https://api.anthropic.com/v1"


async def get_user_llm_provider(
    session: AsyncSession, user_id: uuid.UUID
) -> UserLlmProvider | None:
    result = await session.execute(
        select(UserLlmProvider).where(UserLlmProvider.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def set_user_llm_provider(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    provider: str,
    base_url: str | None,
    model: str,
    api_key: str | None,
) -> UserLlmProvider:
    row = await get_user_llm_provider(session, user_id)
    if api_key is None and row is None:
        raise LlmProviderConfigError("API key required.")
    if row is None:
        row = UserLlmProvider(user_id=user_id)
        session.add(row)
    row.provider = provider
    row.base_url = base_url
    row.model = model
    if api_key is not None:
        row.api_key_encrypted = encrypt_secret(api_key)
    await session.commit()
    await session.refresh(row)
    return row


async def delete_user_llm_provider(
    session: AsyncSession, user_id: uuid.UUID
) -> bool:
    row = await get_user_llm_provider(session, user_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


def config_from_parts(
    *,
    provider: str,
    base_url: str | None,
    model: str,
    api_key: str,
) -> LlmConfig:
    if provider == "gemini":
        return LlmConfig(
            provider="gemini",
            url=f"{GEMINI_API_ROOT}/models/{model}:generateContent",
            headers={},
            params={"key": api_key},
            model=model,
            origin="user",
        )
    if provider == "openai_compatible":
        if not base_url:
            raise LlmProviderConfigError("Base URL is required.")
        root = base_url.rstrip("/")
        return LlmConfig(
            provider="openai_compatible",
            url=f"{root}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            params={},
            model=model,
            origin="user",
            base_url=root,
        )
    if provider == "anthropic":
        return LlmConfig(
            provider="anthropic",
            url=f"{ANTHROPIC_API_ROOT}/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            params={},
            model=model,
            origin="user",
        )
    raise LlmProviderConfigError(f"Unsupported provider: {provider}")


def user_config_to_llm_config(row: UserLlmProvider) -> LlmConfig:
    if row.api_key_encrypted is None:
        raise LlmProviderConfigError("Stored API key is missing.")
    return config_from_parts(
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        api_key=decrypt_secret(row.api_key_encrypted),
    )


async def resolve_llm_config_for_user(
    session: AsyncSession | None,
    user_id: uuid.UUID | None,
    *,
    force_server_default: bool = False,
) -> LlmConfig | None:
    if session is not None and user_id is not None and not force_server_default:
        row = await get_user_llm_provider(session, user_id)
        if row is not None:
            return user_config_to_llm_config(row)
    return resolve_llm_config()
