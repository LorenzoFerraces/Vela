"""User LLM provider storage and config resolution."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import LlmProviderConfigError
from app.core.llm import user_config
from app.core.llm.provider import GEMINI_API_ROOT, endpoint_fingerprint
from app.core.security.secrets import decrypt_secret, reset_token_cipher_for_tests
from app.db.models import User

_NO_SERVER_LLM_VARS = (
    "VELA_VERTEX_API_KEY",
    "VELA_VERTEX_PROJECT_ID",
    "VELA_VERTEX_LOCATION",
    "VELA_VERTEX_MODEL",
    "VELA_GEMINI_API_KEY",
    "VELA_GEMINI_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    reset_token_cipher_for_tests()
    for name in _NO_SERVER_LLM_VARS:
        monkeypatch.delenv(name, raising=False)


async def _make_user(session: AsyncSession, email: str) -> User:
    user = User(email=email)
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_set_and_get_roundtrip(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = await _make_user(session, "provider@example.com")
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="gemini-2.5-flash",
            api_key="sk-user-test",
        )
    async with db_session_factory() as session:
        stored = await user_config.get_user_llm_provider(session, user.id)
        assert stored is not None
        assert stored.provider == "gemini"
        assert stored.model == "gemini-2.5-flash"
        assert stored.api_key_encrypted is not None
        assert decrypt_secret(stored.api_key_encrypted) == "sk-user-test"
        config = user_config.user_config_to_llm_config(stored)
        assert config.origin == "user"
        assert config.url == (
            f"{GEMINI_API_ROOT}/models/gemini-2.5-flash:generateContent"
        )
        assert config.params == {"key": "sk-user-test"}


@pytest.mark.asyncio
async def test_set_without_key_when_none_saved_raises(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = await _make_user(session, "provider2@example.com")
        await session.commit()
        with pytest.raises(LlmProviderConfigError, match="API key required"):
            await user_config.set_user_llm_provider(
                session,
                user.id,
                provider="gemini",
                base_url=None,
                model="gemini-2.5-flash",
                api_key=None,
            )


@pytest.mark.asyncio
async def test_set_without_key_keeps_existing_key(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = await _make_user(session, "provider3@example.com")
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="gemini-2.5-flash",
            api_key="sk-old",
        )
        row = await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="gemini-3.5-flash",
            api_key=None,
        )
        assert row.model == "gemini-3.5-flash"
        assert row.api_key_encrypted is not None
        assert decrypt_secret(row.api_key_encrypted) == "sk-old"


@pytest.mark.asyncio
async def test_set_without_key_when_provider_changes_raises(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = await _make_user(session, "provider-change@example.com")
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="gemini-2.5-flash",
            api_key="sk-old",
        )
        with pytest.raises(LlmProviderConfigError, match="API key required"):
            await user_config.set_user_llm_provider(
                session,
                user.id,
                provider="anthropic",
                base_url=None,
                model="claude-sonnet-4-5",
                api_key=None,
            )


@pytest.mark.asyncio
async def test_set_without_key_when_base_url_changes_raises(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = await _make_user(session, "base-url-change@example.com")
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="openai_compatible",
            base_url="https://one.example/v1",
            model="gpt-4o-mini",
            api_key="sk-old",
        )
        with pytest.raises(LlmProviderConfigError, match="API key required"):
            await user_config.set_user_llm_provider(
                session,
                user.id,
                provider="openai_compatible",
                base_url="https://two.example/v1",
                model="gpt-4o-mini",
                api_key=None,
            )


def test_endpoint_fingerprint_isolates_same_model_different_endpoint() -> None:
    one = user_config.config_from_parts(
        provider="openai_compatible",
        base_url="https://one.example/v1",
        model="gpt-4o-mini",
        api_key="sk",
    )
    two = user_config.config_from_parts(
        provider="openai_compatible",
        base_url="https://two.example/v1",
        model="gpt-4o-mini",
        api_key="sk",
    )
    assert endpoint_fingerprint(one) != endpoint_fingerprint(two)
    assert "sk" not in endpoint_fingerprint(one)


@pytest.mark.asyncio
async def test_delete_roundtrip(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = await _make_user(session, "provider4@example.com")
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="gemini-2.5-flash",
            api_key="sk-x",
        )
        assert await user_config.delete_user_llm_provider(session, user.id) is True
        assert await user_config.get_user_llm_provider(session, user.id) is None
        assert await user_config.delete_user_llm_provider(session, user.id) is False


def test_config_from_parts_openai_compatible() -> None:
    config = user_config.config_from_parts(
        provider="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-4o-mini",
        api_key="sk-or",
    )
    assert config.url == "https://openrouter.ai/api/v1/chat/completions"
    assert config.headers == {"Authorization": "Bearer sk-or"}
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.origin == "user"


def test_config_from_parts_anthropic() -> None:
    config = user_config.config_from_parts(
        provider="anthropic",
        base_url=None,
        model="claude-sonnet-4-5",
        api_key="sk-ant",
    )
    assert config.url == "https://api.anthropic.com/v1/messages"
    assert config.headers == {
        "x-api-key": "sk-ant",
        "anthropic-version": "2023-06-01",
    }


@pytest.mark.asyncio
async def test_resolve_prefers_user_row_over_env(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "env-key")
    async with db_session_factory() as session:
        user = await _make_user(session, "resolve@example.com")
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="user-model",
            api_key="sk-user",
        )
        config = await user_config.resolve_llm_config_for_user(session, user.id)
        assert config is not None
        assert config.origin == "user"
        assert config.model == "user-model"


@pytest.mark.asyncio
async def test_resolve_force_server_default_skips_user_row(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("VELA_GEMINI_MODEL", "server-default-model")
    async with db_session_factory() as session:
        user = await _make_user(session, "force@example.com")
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="user-model",
            api_key="sk-user",
        )
        config = await user_config.resolve_llm_config_for_user(
            session, user.id, force_server_default=True
        )
        assert config is not None
        assert config.origin == "server"
        assert config.model == "server-default-model"


def test_resolve_none_when_nothing_configured() -> None:
    import asyncio

    assert asyncio.run(user_config.resolve_llm_config_for_user(None, None)) is None
