# User LLM Provider (BYO Key) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each user can save one active LLM provider (OpenAI-compatible / Gemini / Anthropic); both AI analysis features use it in preference to the server default, and a user-provider failure offers one-click "Retry with Vela default".

**Architecture:** Provider registry in `app/core/llm/` (`LlmProvider` ABC + 3 wire-format implementations + `match/case` registry). Per-user config in a new `UserLlmProvider` table (Fernet-encrypted key, one row per user). Requests resolve user row > server env; user-origin failures become `LlmProviderError` → 502 `{detail, fallback_available}`. Frontend adds a settings card (save/test/remove) plus retry buttons at the three analysis call sites.

**Tech Stack:** FastAPI + SQLAlchemy 2 async (in-memory SQLite in tests), httpx, Fernet via `cryptography`, Pydantic v2, React 19 + TypeScript, Vite, Playwright.

## Global Constraints

- Spec (behavior source of truth): `docs/superpowers/specs/2026-09-07-user-llm-provider-design.md`.
- Backend tests after every backend task: `cd backend && python -m pytest tests -q` (all pass), plus `ruff check .` and `mypy app/ tests/` clean.
- Frontend after frontend tasks: from `frontend/` run `npm run lint`, `npm run typecheck`, `npm run test:e2e` — all clean.
- The API never returns API keys: read endpoints expose `has_key: bool` only.
- Keys stored Fernet-encrypted via `encrypt_secret`/`decrypt_secret` in `app/core/security/secrets.py` (same pattern as `UserOAuthIdentity`).
- Server-default behavior must not change: `resolve_llm_config()` (env: Vertex > `VELA_GEMINI_API_KEY`), 503 `LlmNotConfiguredError`, the deterministic git-source fallback, and the E2E fixture short-circuits in both analysis functions all stay as-is.
- No new npm dependencies, no new Python dependencies.
- Frontend uses existing CSS classes only (`settings-card`, `auth-form__label`/`auth-form__input`, `btn btn--primary/--ghost/--danger/--sm`, `settings-banner settings-banner--ok/--err`, `containers-source-check--warn`); no raw hex in components.
- E2E: no `page.route` mocking of app flows (AGENTS.md). The new spec only saves/reloads/removes config, which makes no external provider call.
- One commit per task. Message style: `feat: ...`, `test: ...`, `fix: ...`.

---

## File Structure

Backend — new:

- `backend/app/core/llm/providers/__init__.py` — provider exports.
- `backend/app/core/llm/providers/base.py` — `LlmProvider` ABC, shared `get_client()`, shared `generate_json` transport, default `verify` (model listing).
- `backend/app/core/llm/providers/gemini.py` — `GeminiProvider` (today's `client.py` wire format, moved unchanged).
- `backend/app/core/llm/providers/openai_compatible.py` — `OpenAICompatibleProvider`.
- `backend/app/core/llm/providers/anthropic.py` — `AnthropicProvider`.
- `backend/app/core/llm/registry.py` — `get_provider(config) -> LlmProvider`.
- `backend/app/core/llm/user_config.py` — user-row CRUD, `config_from_parts`, `resolve_llm_config_for_user`.
- `backend/alembic/versions/0020_user_llm_provider.py` — migration.
- Tests: `backend/tests/test_llm_user_config.py`, `test_llm_providers.py`, `test_llm_client_errors.py`, `test_llm_user_fallback.py`, `test_llm_provider_routes.py`.

Backend — modified:

- `backend/app/db/models.py` — add `UserLlmProvider`.
- `backend/app/core/exceptions.py` — add `LlmProviderError`, `LlmProviderConfigError`.
- `backend/app/core/llm/provider.py` — `LlmConfig` gains `origin`/`base_url`; add `GEMINI_API_ROOT`.
- `backend/app/core/llm/client.py` — delegate to registry; user-origin `LlmCallError` → `LlmProviderError`.
- `backend/app/api/errors.py` — 502 handler for `LlmProviderError`, 400 handler for `LlmProviderConfigError`.
- `backend/app/api/schemas.py` — `LlmProviderKind`/`LlmProviderGet`/`LlmProviderSet`/`LlmProviderTestRequest`/`LlmProviderTestResponse`; `GeminiConfigStatus.user_provider`; `use_server_default` on `AnalyzeGitSourceRequest` and `AnalyzeRepoRequest`.
- `backend/app/api/routes/settings.py` — GET/PUT/DELETE `/llm-provider`, POST `/llm-provider/test`, `gemini-status` gains `user_provider`.
- `backend/app/api/routes/builder.py` — thread session/user/flag into `analyze_git_source`.
- `backend/app/api/routes/stacks.py` — same for `analyze_repo_stack`.
- `backend/app/core/git/git_source_analysis.py` — resolve config, thread it, cache version includes provider+model, `use_server_default`.
- `backend/app/core/stacks/repo_analysis.py` — same.
- Existing tests: `backend/tests/test_llm_cache.py`, `test_stack_repo_analysis.py`, `test_stacks_llm_eval.py` (fake signatures + env key).

Frontend — new:

- `frontend/src/api/llmErrors.ts` — `isLlmFallbackError(error: unknown): boolean`.
- `frontend/src/pages/settings/LlmProviderCard.tsx` — save/test/remove card.
- `frontend/e2e/llm-provider.spec.ts` — save/reload/remove E2E.

Frontend — modified:

- `frontend/src/api/settings.ts` — types + `getLlmProvider`/`putLlmProvider`/`deleteLlmProvider`/`testLlmProvider`; `GeminiConfigStatus` gains `user_provider`.
- `frontend/src/api/client.ts` — re-export new symbols.
- `frontend/src/api/builds.ts`, `frontend/src/api/stacks.ts` — `use_server_default?` on analyze bodies.
- `frontend/src/pages/SettingsPage.tsx` — render card above AI card; `AiPrefillSettingsCard` copy + `refreshKey`.
- Retry surface: `frontend/src/pages/containers/useGitSourceAnalysis.ts`, `useContainerRunForm.ts`, `ContainersRunFormFields.tsx`, `frontend/src/pages/ContainersPage.tsx`, `frontend/src/pages/stacks/NewStackModal.tsx`, `ServiceEditForm.tsx`.

---

## Task 1: `LlmConfig` shape, `UserLlmProvider` model + migration, user-config service

**Files:**
- Modify: `backend/app/core/llm/provider.py` (whole file, 50 lines today)
- Modify: `backend/app/core/exceptions.py:161-163` (insert after `LlmCallError`)
- Modify: `backend/app/db/models.py:116` (insert after `UserOAuthIdentity`, before `Dockerfile`)
- Create: `backend/alembic/versions/0020_user_llm_provider.py`
- Create: `backend/app/core/llm/user_config.py`
- Test: `backend/tests/test_llm_user_config.py`

**Interfaces:**
- Consumes: existing `encrypt_secret`/`decrypt_secret`/`reset_token_cipher_for_tests` (`app.core.security.secrets`), `resolve_llm_config()` (`app.core.llm.provider`), conftest fixture `db_session_factory` (in-memory SQLite, `Base.metadata.create_all`).
- Produces (used by all later tasks):
  - `LlmConfig(provider: str, url: str, headers: dict[str, str], params: dict[str, str], model: str, origin: str = "server", base_url: str | None = None)` — frozen dataclass in `app.core.llm.provider`.
  - `GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"` — `app.core.llm.provider`.
  - `UserLlmProvider` ORM model — PK `user_id` (FK `users.id` CASCADE), columns `provider: str(32)`, `base_url: str(1024) | None`, `model: str(255)`, `api_key_encrypted: bytes | None`, `created_at`, `updated_at`.
  - `app.core.llm.user_config`:
    - `async get_user_llm_provider(session: AsyncSession, user_id: uuid.UUID) -> UserLlmProvider | None`
    - `async set_user_llm_provider(session, user_id, *, provider: str, base_url: str | None, model: str, api_key: str | None) -> UserLlmProvider` — raises `LlmProviderConfigError("API key required.")` when `api_key is None` and no row exists; `api_key None` with an existing row keeps the stored key.
    - `async delete_user_llm_provider(session, user_id) -> bool`
    - `config_from_parts(*, provider: str, base_url: str | None, model: str, api_key: str) -> LlmConfig` — `origin="user"`.
    - `user_config_to_llm_config(row: UserLlmProvider) -> LlmConfig` — decrypts.
    - `async resolve_llm_config_for_user(session: AsyncSession | None, user_id: uuid.UUID | None, *, force_server_default: bool = False) -> LlmConfig | None` — user row (unless forced) > env > `None`; `session is None` → env only.
    - `DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"`, `ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-5"`, `ANTHROPIC_API_ROOT = "https://api.anthropic.com/v1"`.
  - `app.core.exceptions`: `LlmProviderError(message: str, *, fallback_available: bool)` (attribute `fallback_available`), `LlmProviderConfigError(message: str)`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_user_config.py`:

```python
"""User LLM provider storage and config resolution."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import LlmProviderConfigError
from app.core.llm import user_config
from app.core.llm.provider import GEMINI_API_ROOT
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


def _make_user(session: AsyncSession, email: str) -> User:
    user = User(email=email)
    session.add(user)
    session.flush()
    return user


@pytest.mark.asyncio
async def test_set_and_get_roundtrip(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = _make_user(session, "provider@example.com")
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
        user = _make_user(session, "provider2@example.com")
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
        user = _make_user(session, "provider3@example.com")
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
        assert decrypt_secret(row.api_key_encrypted) == "sk-old"


@pytest.mark.asyncio
async def test_delete_roundtrip(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = _make_user(session, "provider4@example.com")
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
        user = _make_user(session, "resolve@example.com")
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
    async with db_session_factory() as session:
        user = _make_user(session, "force@example.com")
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
        assert config.model == "gemini-3.5-flash"


def test_resolve_none_when_nothing_configured() -> None:
    import asyncio

    assert asyncio.run(user_config.resolve_llm_config_for_user(None, None)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_llm_user_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.llm.user_config'` (collection error).

- [ ] **Step 3: Implement the model, migration, and user-config service**

**3a. `backend/app/core/llm/provider.py`** — replace the whole file (adds `GEMINI_API_ROOT`, `origin`, `base_url`; gemini URL now uses the constant — no behavior change):

```python
from __future__ import annotations

import os
from dataclasses import dataclass

GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    url: str
    headers: dict[str, str]
    params: dict[str, str]
    model: str
    origin: str = "server"
    base_url: str | None = None


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def resolve_llm_config() -> LlmConfig | None:
    vertex_api_key = _env("VELA_VERTEX_API_KEY")
    vertex_project_id = _env("VELA_VERTEX_PROJECT_ID")
    if vertex_api_key and vertex_project_id:
        location = _env("VELA_VERTEX_LOCATION") or "us-central1"
        model = _env("VELA_VERTEX_MODEL") or "gemini-2.5-flash"
        return LlmConfig(
            provider="vertex",
            url=(
                f"https://{location}-aiplatform.googleapis.com/v1/projects/"
                f"{vertex_project_id}/locations/{location}/publishers/google/"
                f"models/{model}:generateContent"
            ),
            headers={"x-goog-api-key": vertex_api_key},
            params={},
            model=model,
        )

    gemini_api_key = _env("VELA_GEMINI_API_KEY")
    if gemini_api_key:
        model = _env("VELA_GEMINI_MODEL") or "gemini-3.5-flash"
        return LlmConfig(
            provider="gemini",
            url=f"{GEMINI_API_ROOT}/models/{model}:generateContent",
            headers={},
            params={"key": gemini_api_key},
            model=model,
        )

    return None
```

**3b. `backend/app/core/exceptions.py`** — insert after the `LlmCallError` class (line 163):

```python
class LlmProviderError(VelaError):
    """A user-configured LLM provider failed; the server default may still work."""

    def __init__(self, message: str, *, fallback_available: bool) -> None:
        super().__init__(message)
        self.fallback_available = fallback_available


class LlmProviderConfigError(VelaError):
    """User LLM provider settings are invalid or incomplete."""
```

**3c. `backend/app/db/models.py`** — insert after the `UserOAuthIdentity` class (line 116), before `Dockerfile` (all names already imported in this file):

```python
class UserLlmProvider(Base):
    """One active LLM provider per user (BYO key for AI analysis)."""

    __tablename__ = "user_llm_providers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
```

**3d. `backend/alembic/versions/0020_user_llm_provider.py`** — new file (head today is `0019_merge_resource_management`, verified via `alembic heads`):

```python
"""user llm provider

Revision ID: 0020_user_llm_provider
Revises: 0019_merge_resource_management
Create Date: 2026-09-07

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0020_user_llm_provider"
down_revision: str | Sequence[str] | None = "0019_merge_resource_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_llm_providers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_llm_providers")
```

**3e. `backend/app/core/llm/user_config.py`** — new file:

```python
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
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_llm_user_config.py -q`
Expected: all pass (9 tests).

- [ ] **Step 5: Lint and typecheck**

Run: `cd backend && ruff check . && mypy app/ tests/`
Expected: clean.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/llm/provider.py backend/app/core/exceptions.py backend/app/db/models.py backend/alembic/versions/0020_user_llm_provider.py backend/app/core/llm/user_config.py backend/tests/test_llm_user_config.py
git commit -m "feat: user LLM provider model, migration and config service"
```

---

## Task 2: Provider package (`LlmProvider` ABC + 3 implementations + registry)

**Files:**
- Create: `backend/app/core/llm/providers/__init__.py`
- Create: `backend/app/core/llm/providers/base.py`
- Create: `backend/app/core/llm/providers/gemini.py`
- Create: `backend/app/core/llm/providers/openai_compatible.py`
- Create: `backend/app/core/llm/providers/anthropic.py`
- Create: `backend/app/core/llm/registry.py`
- Test: `backend/tests/test_llm_providers.py`

**Interfaces:**
- Consumes: `LlmConfig` (`app.core.llm.provider`, incl. `GEMINI_API_ROOT`), `LlmCallError` (`app.core.exceptions`).
- Produces:
  - `LlmProvider` ABC (`app.core.llm.providers.base`) with abstract `build_request(config, prompt, schema) -> dict` and `extract_text(body) -> str`; overridable `prepare_prompt(prompt, config) -> str` (identity), `parse_json_text(text) -> dict` (json.loads, dict-only), `models_url(config) -> str | None` (None); concrete shared `async generate_json(config, *, prompt, schema) -> dict` (POST → `extract_text` → `parse_json_text`; `httpx.HTTPError` → `LlmCallError("Could not complete AI analysis. Try again later.")`, parse failures → `LlmCallError("AI analysis returned an invalid response. Try again later.")`) and `async verify(config) -> list[str] | None` (GET `models_url`, parses `{"models": [{"name"}]}` stripping the `models/` prefix or `{"data": [{"id"}]}`; httpx error → `LlmCallError("Could not reach the provider.")` with the httpx exception as `__cause__`; returns `None` when `models_url` is None). Module-level `get_client()` (60s timeout) — providers must call `base.get_client()` at call time so tests can monkeypatch `app.core.llm.providers.base.get_client`.
  - `GeminiProvider` (today's `client.py` wire format), `OpenAICompatibleProvider` (chat completions + `response_format: json_object`), `AnthropicProvider` (Messages API, `max_tokens: 8192`, fence-stripping parse, verify = 1-token Messages POST returning `None`).
  - `get_provider(config: LlmConfig) -> LlmProvider` (`app.core.llm.registry`): `"gemini" | "vertex"` → Gemini, `"openai_compatible"` → OpenAI-compatible, `"anthropic"` → Anthropic, else `LlmCallError(f"Unsupported LLM provider: {config.provider}")`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_llm_providers.py`:

```python
"""Provider wire formats, shared transport, and registry dispatch."""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.exceptions import LlmCallError
from app.core.llm.provider import LlmConfig
from app.core.llm.providers import base
from app.core.llm.providers.anthropic import AnthropicProvider
from app.core.llm.providers.gemini import GeminiProvider
from app.core.llm.providers.openai_compatible import OpenAICompatibleProvider
from app.core.llm.registry import get_provider

GEMINI_BODY = {
    "candidates": [{"content": {"parts": [{"text": '{"ok": 1}'}]}}]
}


def _gemini_config() -> LlmConfig:
    return LlmConfig(
        provider="gemini",
        url="https://generativelanguage.googleapis.com/v1beta/models/m:generateContent",
        headers={},
        params={"key": "k"},
        model="m",
        origin="user",
    )


def _openai_config() -> LlmConfig:
    return LlmConfig(
        provider="openai_compatible",
        url="https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer sk"},
        params={},
        model="gpt-4o-mini",
        origin="user",
        base_url="https://api.openai.com/v1",
    )


def _anthropic_config() -> LlmConfig:
    return LlmConfig(
        provider="anthropic",
        url="https://api.anthropic.com/v1/messages",
        headers={"x-api-key": "sk", "anthropic-version": "2023-06-01"},
        params={},
        model="claude-sonnet-4-5",
        origin="user",
    )


class _FakeResponse:
    def __init__(self, payload: dict | None, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://provider.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse | Exception):
        self.response = response
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    async def post(self, url, headers=None, params=None, json=None):
        self.posts.append(
            {"url": url, "headers": headers, "params": params, "json": json}
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def get(self, url, headers=None, params=None):
        self.gets.append({"url": url, "headers": headers, "params": params})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _use(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    monkeypatch.setattr(base, "get_client", lambda: client)


def test_gemini_wire_format_matches_current_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_FakeResponse(GEMINI_BODY))
    _use(monkeypatch, client)
    import asyncio

    parsed = asyncio.run(GeminiProvider().generate_json(
        _gemini_config(), prompt="P", schema={"type": "OBJECT"}
    ))
    assert parsed == {"ok": 1}
    posted = client.posts[0]
    assert posted["json"] == {
        "contents": [{"role": "user", "parts": [{"text": "P"}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {"type": "OBJECT"},
        },
    }


def test_openai_wire_format(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"choices": [{"message": {"content": '{"ok": 2}'}}]}
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    parsed = asyncio.run(OpenAICompatibleProvider().generate_json(
        _openai_config(), prompt="P", schema={}
    ))
    assert parsed == {"ok": 2}
    posted = client.posts[0]
    assert posted["json"]["model"] == "gpt-4o-mini"
    assert posted["json"]["response_format"] == {"type": "json_object"}
    assert posted["json"]["messages"] == [{"role": "user", "content": posted["json"]["messages"][0]["content"]}][:1]
    assert "JSON" in posted["json"]["messages"][0]["content"]


def test_anthropic_wire_format_and_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {
        "content": [
            {"type": "text", "text": '```json\n{"ok": 3}\n```'},
        ]
    }
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    parsed = asyncio.run(AnthropicProvider().generate_json(
        _anthropic_config(), prompt="P", schema={}
    ))
    assert parsed == {"ok": 3}
    posted = client.posts[0]
    assert posted["json"]["max_tokens"] == 8192
    assert posted["json"]["messages"] == [{"role": "user", "content": posted["json"]["messages"][0]["content"]}]
    assert posted["url"] == "https://api.anthropic.com/v1/messages"


def test_http_error_raises_llm_call_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = httpx.HTTPStatusError(
        "boom",
        request=httpx.Request("POST", "https://x"),
        response=httpx.Response(401, request=httpx.Request("POST", "https://x")),
    )
    client = _FakeClient(error)
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="Could not complete AI analysis"):
        asyncio.run(GeminiProvider().generate_json(_gemini_config(), prompt="P", schema={}))


def test_malformed_body_raises_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_FakeResponse({"candidates": []}))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="invalid response"):
        asyncio.run(GeminiProvider().generate_json(_gemini_config(), prompt="P", schema={}))


def test_non_dict_json_raises_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"candidates": [{"content": {"parts": [{"text": "42"}]}}]}
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="invalid response"):
        asyncio.run(GeminiProvider().generate_json(_gemini_config(), prompt="P", schema={}))


def test_verify_parses_gemini_model_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"models": [{"name": "models/gemini-a"}, {"name": "gemini-b"}]}
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    names = asyncio.run(GeminiProvider().verify(_gemini_config()))
    assert names == ["gemini-a", "gemini-b"]
    assert client.gets[0]["params"] == {"key": "k"}


def test_verify_parses_openai_model_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}
    client = _FakeClient(_FakeResponse(body))
    _use(monkeypatch, client)
    import asyncio

    names = asyncio.run(OpenAICompatibleProvider().verify(_openai_config()))
    assert names == ["gpt-4o", "gpt-4o-mini"]
    assert client.gets[0]["url"] == "https://api.openai.com/v1/models"


def test_verify_connection_error_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(httpx.ConnectError("down"))
    _use(monkeypatch, client)
    import asyncio

    with pytest.raises(LlmCallError, match="Could not reach the provider"):
        asyncio.run(GeminiProvider().verify(_gemini_config()))


def test_anthropic_verify_posts_one_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_FakeResponse({"content": [{"type": "text", "text": "x"}]}))
    _use(monkeypatch, client)
    import asyncio

    assert asyncio.run(AnthropicProvider().verify(_anthropic_config())) is None
    assert client.posts[0]["json"]["max_tokens"] == 1


def test_registry_dispatches() -> None:
    assert isinstance(get_provider(_gemini_config()), GeminiProvider)
    vertex = _gemini_config()
    assert isinstance(
        get_provider(LlmConfig(
            provider="vertex", url=vertex.url, headers=vertex.headers,
            params={}, model=vertex.model,
        )),
        GeminiProvider,
    )
    assert isinstance(get_provider(_openai_config()), OpenAICompatibleProvider)
    assert isinstance(get_provider(_anthropic_config()), AnthropicProvider)
    unknown = LlmConfig(
        provider="mystery", url="u", headers={}, params={}, model="m"
    )
    with pytest.raises(LlmCallError, match="Unsupported LLM provider"):
        get_provider(unknown)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_llm_providers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.llm.providers'`.

- [ ] **Step 3: Implement the provider package**

**`backend/app/core/llm/providers/base.py`**:

```python
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
```

**`backend/app/core/llm/providers/gemini.py`**:

```python
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
```

**`backend/app/core/llm/providers/openai_compatible.py`**:

```python
from __future__ import annotations

from app.core.llm.provider import LlmConfig
from app.core.llm.providers.base import LlmProvider

_JSON_ONLY_TAIL = (
    "\n\nRespond with a single valid JSON object only. No prose, no markdown fences."
)


class OpenAICompatibleProvider(LlmProvider):
    def build_request(self, config: LlmConfig, prompt: str, schema: dict) -> dict:
        # ponytail: the schema is Gemini responseSchema-shaped, so chat providers
        # rely on the prompt's field descriptions + the JSON-only tail, not the schema.
        return {
            "model": config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }

    def prepare_prompt(self, prompt: str, config: LlmConfig) -> str:
        return prompt + _JSON_ONLY_TAIL

    def extract_text(self, body: dict) -> str:
        text = body["choices"][0]["message"]["content"]
        if not isinstance(text, str):
            raise TypeError("LLM response text must be a string.")
        return text

    def models_url(self, config: LlmConfig) -> str | None:
        if not config.base_url:
            return None
        return f"{config.base_url}/models"
```

**`backend/app/core/llm/providers/anthropic.py`**:

```python
from __future__ import annotations

from app.core.llm.provider import LlmConfig
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
        try:
            response = await get_client().post(
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
```

(`anthropic.py` also imports `httpx`, `LlmCallError` from `app.core.exceptions`, and `get_client` from `app.core.llm.providers.base`.)

**`backend/app/core/llm/registry.py`**:

```python
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
```

**`backend/app/core/llm/providers/__init__.py`**:

```python
from app.core.llm.providers.anthropic import AnthropicProvider
from app.core.llm.providers.base import LlmProvider
from app.core.llm.providers.gemini import GeminiProvider
from app.core.llm.providers.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "AnthropicProvider",
    "GeminiProvider",
    "LlmProvider",
    "OpenAICompatibleProvider",
]
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_llm_providers.py -q`
Expected: all pass (11 tests).

- [ ] **Step 5: Lint and typecheck**

Run: `cd backend && ruff check . && mypy app/ tests/`
Expected: clean.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/llm/providers backend/app/core/llm/registry.py backend/tests/test_llm_providers.py
git commit -m "feat: LLM provider registry with gemini, openai-compatible and anthropic wire formats"
```

---

## Task 3: `client.py` dispatch + `LlmProviderError` mapping + API handlers

**Files:**
- Modify: `backend/app/core/llm/client.py` (whole file, 84 lines today)
- Modify: `backend/app/api/errors.py` (import block ~line 40; new handlers after `llm_analysis_handler` ~line 391)
- Test: `backend/tests/test_llm_client_errors.py`

**Interfaces:**
- Consumes: `get_provider` (Task 2), `LlmProviderError`/`LlmProviderConfigError` (Task 1), `LlmConfig.origin`.
- Produces:
  - `async generate_json(*, prompt: str, schema: dict, config: LlmConfig | None = None) -> dict` — `config None` → `resolve_llm_config()` (unchanged server behavior); `None` result → `LlmNotConfiguredError("AI analysis is not configured on this server.")`; dispatches via `get_provider(resolved)`; on `LlmCallError` with `resolved.origin == "user"` re-raises `LlmProviderError(str(exc), fallback_available=resolve_llm_config() is not None)`; server-origin errors propagate as `LlmCallError` (→ 503, unchanged).
  - API: `LlmProviderError` → 502 `{"detail": str(exc), "fallback_available": bool}`; `LlmProviderConfigError` → 400 `{"detail": str(exc)}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_llm_client_errors.py`:

```python
"""generate_json registry dispatch and user-provider failure mapping."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.exceptions import (
    LlmCallError,
    LlmNotConfiguredError,
    LlmProviderError,
)
from app.core.llm.client import generate_json
from app.core.llm.provider import LlmConfig
from app.core.llm.providers import base

_NO_LLM_VARS = (
    "VELA_VERTEX_API_KEY",
    "VELA_VERTEX_PROJECT_ID",
    "VELA_VERTEX_LOCATION",
    "VELA_VERTEX_MODEL",
    "VELA_GEMINI_API_KEY",
    "VELA_GEMINI_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _NO_LLM_VARS:
        monkeypatch.delenv(name, raising=False)


def _config(origin: str) -> LlmConfig:
    return LlmConfig(
        provider="gemini",
        url="https://generativelanguage.googleapis.com/v1beta/models/m:generateContent",
        headers={},
        params={"key": "k"},
        model="m",
        origin=origin,
    )


class _ErrorClient:
    def __init__(self, error: Exception):
        self.error = error

    async def post(self, url, headers=None, params=None, json=None):
        raise self.error


class _OkClient:
    async def post(self, url, headers=None, params=None, json=None):
        class _Response:
            status_code = 200
            text = "{}"

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "candidates": [
                        {"content": {"parts": [{"text": '{"ok": 1}'}]}}
                    ]
                }

        return _Response()


def _use(monkeypatch: pytest.MonkeyPatch, client: object) -> None:
    monkeypatch.setattr(base, "get_client", lambda: client)


def _http_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.test")
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(401, request=request)
    )


def test_server_origin_error_stays_llm_call_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _ErrorClient(_http_error()))
    with pytest.raises(LlmCallError, match="Could not complete AI analysis"):
        asyncio.run(
            generate_json(prompt="P", schema={}, config=_config("server"))
        )


def test_user_origin_error_becomes_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "env-key")
    _use(monkeypatch, _ErrorClient(_http_error()))
    with pytest.raises(LlmProviderError) as excinfo:
        asyncio.run(generate_json(prompt="P", schema={}, config=_config("user")))
    assert excinfo.value.fallback_available is True


def test_user_origin_error_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _ErrorClient(_http_error()))
    with pytest.raises(LlmProviderError) as excinfo:
        asyncio.run(generate_json(prompt="P", schema={}, config=_config("user")))
    assert excinfo.value.fallback_available is False


def test_unconfigured_raises_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _ErrorClient(_http_error()))
    with pytest.raises(LlmNotConfiguredError, match="not configured"):
        asyncio.run(generate_json(prompt="P", schema={}))


def test_dispatches_to_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _OkClient())
    assert (
        asyncio.run(
            generate_json(prompt="P", schema={}, config=_config("user"))
        )
        == {"ok": 1}
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_llm_client_errors.py -q`
Expected: FAIL — current `generate_json` has no `config` parameter (`TypeError`).

- [ ] **Step 3: Implement**

**`backend/app/core/llm/client.py`** — replace the whole file:

```python
from __future__ import annotations

import logging

from app.core.exceptions import (
    LlmCallError,
    LlmNotConfiguredError,
    LlmProviderError,
)
from app.core.llm.provider import LlmConfig, resolve_llm_config
from app.core.llm.registry import get_provider

logger = logging.getLogger(__name__)


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
```

**`backend/app/api/errors.py`** — add `LlmProviderConfigError` and `LlmProviderError` to the `from app.core.exceptions import (...)` block (alphabetical position among the `Llm*` names), then insert after the `llm_analysis_handler` block:

```python
    @app.exception_handler(LlmProviderError)
    async def llm_provider_error_handler(
        _request: Request, exc: LlmProviderError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "detail": str(exc),
                "fallback_available": exc.fallback_available,
            },
        )

    @app.exception_handler(LlmProviderConfigError)
    async def llm_provider_config_error_handler(
        _request: Request, exc: LlmProviderConfigError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )
```

- [ ] **Step 4: Run tests and verify green**

Run: `cd backend && python -m pytest tests -q`
Expected: ALL pass (existing flows still call `generate_json(prompt=..., schema=...)` — the `config=None` path preserves today's behavior).

- [ ] **Step 5: Lint and typecheck**

Run: `cd backend && ruff check . && mypy app/ tests/`
Expected: clean.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/llm/client.py backend/app/api/errors.py backend/tests/test_llm_client_errors.py
git commit -m "feat: route LLM calls through provider registry; map user-provider failures to 502"
```

---

## Task 4: Git-source flow uses user provider + `use_server_default`

**Files:**
- Modify: `backend/app/core/git/git_source_analysis.py` (imports 16-26, `_call_gemini` 616-658, `analyze_git_source` 716-774)
- Modify: `backend/app/api/routes/builder.py` (`analyze_git_source_route` 50-65)
- Modify: `backend/app/api/schemas.py` (`AnalyzeGitSourceRequest` 417)
- Modify: `backend/tests/test_llm_cache.py` (fakes at 221/257 gain `config`; `test_git_source_invalid_payload_is_not_cached` ~288 gains env key)
- Test: `backend/tests/test_llm_user_fallback.py` (git section)

**Interfaces:**
- Consumes: `resolve_llm_config_for_user` (Task 1), `generate_json(config=...)` (Task 3), `LlmConfig` (Task 1).
- Produces:
  - `analyze_git_source(image_builder, *, git_url, git_branch, access_token, session: AsyncSession | None = None, user_id: uuid.UUID | None = None, use_server_default: bool = False) -> GitSourceAnalysis` — resolves config via `resolve_llm_config_for_user(session, user_id, force_server_default=use_server_default)`; `None` → deterministic fallback (unchanged); cache version becomes `f"{GIT_SOURCE_PROMPT_VERSION}:{config.provider}:{config.model}"` (passed to `load_cached`/`store_cached`/`delete_cached` in place of the bare `GIT_SOURCE_PROMPT_VERSION`).
  - `_call_gemini(context, git_url, git_branch, facts = "", commit = "", config: LlmConfig | None = None)` — `config None` → `resolve_llm_config()`; still `None` → `GitSourceAnalysisError("AI analysis is not configured on this server.")`; passes `config=config` to `generate_json`; drops the now-dead `except LlmNotConfiguredError` clause (keeps the `except LlmCallError` message mapping); `LlmProviderError` propagates untouched (→ 502).
  - `AnalyzeGitSourceRequest.use_server_default: bool = False`.
- Notes: `LlmProviderError` is NOT caught by the flow's `except LlmCallError` handlers (distinct class), so user-provider failures reach the 502 handler with `fallback_available`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_llm_user_fallback.py` (git section; the stacks section is appended in Task 5):

```python
"""User-provider resolution and fallback behavior in the analysis flows."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.build.default_image_builder import DefaultImageBuilder
from app.core.exceptions import LlmProviderError
from app.core.git import git_source_analysis
from app.core.llm import user_config
from app.core.llm.provider import LlmConfig
from app.db.models import User

_NO_LLM_VARS = (
    "VELA_VERTEX_API_KEY",
    "VELA_VERTEX_PROJECT_ID",
    "VELA_VERTEX_LOCATION",
    "VELA_VERTEX_MODEL",
    "VELA_GEMINI_API_KEY",
    "VELA_GEMINI_MODEL",
)

USER_CONFIG = LlmConfig(
    provider="gemini",
    url="https://generativelanguage.googleapis.com/v1beta/models/user-model:generateContent",
    headers={},
    params={"key": "sk-user"},
    model="user-model",
    origin="user",
)

VALID_PAYLOAD = {
    "git_branch": "main",
    "container_port": 8000,
    "container_name": "repo",
    "env_var_entries": [],
    "start_command": None,
    "language": "python",
    "framework": None,
    "has_dockerfile": False,
    "build_strategy": "generated_dockerfile",
    "summary_hint": "ok",
}


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELA_E2E", raising=False)
    for name in _NO_LLM_VARS:
        monkeypatch.delenv(name, raising=False)


def _record_fake(record: dict):
    async def fake_generate_json(
        *, prompt: str, schema: dict, config: LlmConfig | None = None
    ) -> dict:
        record["config"] = config
        return dict(VALID_PAYLOAD)

    return fake_generate_json


async def fake_head_ref(*, url: str, branch: str, access_token: str | None = None) -> str:
    return "abc123"


class _StubBuilder(DefaultImageBuilder):
    def __init__(self, tmp_dir: Path) -> None:
        self._tmp_dir = tmp_dir
        self._counter = 0

    async def clone_repository(
        self, git_url: str, *, branch: str = "main", access_token: str | None = None
    ) -> str:
        _ = git_url, branch, access_token
        self._counter += 1
        dest = self._tmp_dir / f"clone-{self._counter}" / "repo"
        dest.mkdir(parents=True, exist_ok=True)
        return str(dest)


def test_call_gemini_uses_explicit_user_config(monkeypatch: pytest.MonkeyPatch) -> None:
    record: dict = {}
    monkeypatch.setattr(git_source_analysis, "generate_json", _record_fake(record))
    analysis = asyncio.run(
        git_source_analysis._call_gemini(
            "context", "https://github.com/o/r.git", "main", config=USER_CONFIG
        )
    )
    assert record["config"] is USER_CONFIG
    assert analysis.container_port == 8000


def test_call_gemini_without_config_or_env_raises_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("generate_json must not run without a config")

    monkeypatch.setattr(git_source_analysis, "generate_json", _no_call)
    with pytest.raises(
        git_source_analysis.GitSourceAnalysisError, match="not configured"
    ):
        asyncio.run(
            git_source_analysis._call_gemini(
                "context", "https://github.com/o/r.git", "main"
            )
        )


def test_call_gemini_user_provider_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*, prompt: str, schema: dict, config: LlmConfig | None = None) -> dict:
        raise LlmProviderError(
            "Could not complete AI analysis. Try again later.",
            fallback_available=True,
        )

    monkeypatch.setattr(git_source_analysis, "generate_json", _boom)
    with pytest.raises(LlmProviderError) as excinfo:
        asyncio.run(
            git_source_analysis._call_gemini(
                "context", "https://github.com/o/r.git", "main", config=USER_CONFIG
            )
        )
    assert excinfo.value.fallback_available is True


@pytest.mark.asyncio
async def test_analyze_git_source_prefers_user_row_over_env(
    db_session_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("VELA_LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(git_source_analysis, "git_head_ref", fake_head_ref)
    record: dict = {}
    monkeypatch.setattr(git_source_analysis, "generate_json", _record_fake(record))
    async with db_session_factory() as session:
        user = User(email="flow@example.com")
        session.add(user)
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="user-model",
            api_key="sk-user",
        )
        await git_source_analysis.analyze_git_source(
            _StubBuilder(tmp_path),
            git_url="https://github.com/o/r.git",
            git_branch="main",
            access_token=None,
            session=session,
            user_id=user.id,
        )
    assert record["config"] is not None
    assert record["config"].origin == "user"
    assert record["config"].model == "user-model"


@pytest.mark.asyncio
async def test_analyze_git_source_use_server_default_skips_user_row(
    db_session_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("VELA_LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(git_source_analysis, "git_head_ref", fake_head_ref)
    record: dict = {}
    monkeypatch.setattr(git_source_analysis, "generate_json", _record_fake(record))
    async with db_session_factory() as session:
        user = User(email="force@example.com")
        session.add(user)
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="user-model",
            api_key="sk-user",
        )
        await git_source_analysis.analyze_git_source(
            _StubBuilder(tmp_path),
            git_url="https://github.com/o/r.git",
            git_branch="main",
            access_token=None,
            session=session,
            user_id=user.id,
            use_server_default=True,
        )
    assert record["config"] is not None
    assert record["config"].origin == "server"
    assert record["config"].model == "gemini-3.5-flash"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_llm_user_fallback.py -q`
Expected: FAIL — `_call_gemini` has no `config` parameter; `analyze_git_source` has no `session`/`user_id`/`use_server_default` parameters (`TypeError`).

- [ ] **Step 3: Implement**

**`backend/app/core/git/git_source_analysis.py`** — four edits:

1. Imports — add `import uuid` (top, with the stdlib imports); drop `LlmNotConfiguredError` from the `app.core.exceptions` import (keep `GitSourceAnalysisError`, `LlmCallError`); add `from sqlalchemy.ext.asyncio import AsyncSession`; change the llm import block to:

```python
from app.core.llm import generate_json
from app.core.llm.provider import LlmConfig, resolve_llm_config
from app.core.llm.user_config import resolve_llm_config_for_user
```

2. `_call_gemini` — new signature and config resolution (replace the `def _call_gemini(...)` header and its first lines):

```python
async def _call_gemini(
    context: str,
    git_url: str,
    git_branch: str,
    facts: str = "",
    commit: str = "",
    config: LlmConfig | None = None,
) -> GitSourceAnalysis:
    if config is None:
        config = resolve_llm_config()
    if config is None:
        raise GitSourceAnalysisError(
            "AI analysis is not configured on this server."
        )
```

Then in the body: replace `parsed = await generate_json(prompt=prompt, schema=_analysis_json_schema())` with `parsed = await generate_json(prompt=prompt, schema=_analysis_json_schema(), config=config)`, and delete the `except LlmNotConfiguredError as exc: ... from exc` clause (keep the `except LlmCallError` clause exactly as-is).

3. `analyze_git_source` — new signature:

```python
async def analyze_git_source(
    image_builder: DefaultImageBuilder,
    *,
    git_url: str,
    git_branch: str,
    access_token: str | None,
    session: AsyncSession | None = None,
    user_id: uuid.UUID | None = None,
    use_server_default: bool = False,
) -> GitSourceAnalysis:
```

After the e2e-fixture early return, replace `if resolve_llm_config() is None:` with:

```python
    config = await resolve_llm_config_for_user(
        session, user_id, force_server_default=use_server_default
    )
    if config is None:
```

(keep the existing fallback block under it). After the fallback block, add `cache_version = f"{GIT_SOURCE_PROMPT_VERSION}:{config.provider}:{config.model}"`, then in the LLM path replace the three bare `GIT_SOURCE_PROMPT_VERSION` cache arguments (`load_cached(...)`, `delete_cached(...)`, `store_cached(...)`) with `cache_version`, and pass `config=config` to the `_call_gemini(...)` call.

4. **`backend/app/api/routes/builder.py`** — in `analyze_git_source_route`, extend the `analyze_git_source(...)` call:

```python
    return await analyze_git_source(
        image_builder,
        git_url=git_url,
        git_branch=body.git_branch.strip() or "main",
        access_token=access_token,
        session=session,
        user_id=current_user.id,
        use_server_default=body.use_server_default,
    )
```

5. **`backend/app/api/schemas.py`** — extend `AnalyzeGitSourceRequest`:

```python
class AnalyzeGitSourceRequest(BaseModel):
    git_url: str = Field(..., min_length=1, max_length=2048)
    git_branch: str = Field(default="main", max_length=256)
    use_server_default: bool = False
```

**`backend/tests/test_llm_cache.py`** — three updates:

- Both `fake_generate_json` definitions (the ones at ~line 221 and ~257 inside `test_git_source_cache_key_includes_requested_branch` and `test_git_source_cache_key_isolates_distinct_repositories`) gain the `config` parameter:

```python
    async def fake_generate_json(
        *, prompt: str, schema: dict, config: LlmConfig | None = None
    ) -> dict:
```

  (add `from app.core.llm.provider import LlmConfig` to the imports).
- `test_git_source_invalid_payload_is_not_cached` (~line 288) — its direct `_call_gemini` call would otherwise hit "not configured" before the bad payload; add next to its monkeypatch:

```python
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "test-key")
```

  and extend its `bad_generate_json` signature with `config: LlmConfig | None = None`.

- [ ] **Step 4: Run tests and verify green**

Run: `cd backend && python -m pytest tests -q`
Expected: ALL pass (git flow honors user row; server behavior and cache tests unchanged).

- [ ] **Step 5: Lint and typecheck**

Run: `cd backend && ruff check . && mypy app/ tests/`
Expected: clean.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/git/git_source_analysis.py backend/app/api/routes/builder.py backend/app/api/schemas.py backend/tests/test_llm_cache.py backend/tests/test_llm_user_fallback.py
git commit -m "feat: git-source analysis uses the user's LLM provider with one-click default retry"
```

---

## Task 5: Stack repo-analysis flow uses user provider + `use_server_default`

**Files:**
- Modify: `backend/app/core/stacks/repo_analysis.py` (imports 3-31, `_generate_services` 289-341, `analyze_repo_stack` 344-410)
- Modify: `backend/app/api/routes/stacks.py` (`analyze_repo_route` 142-164)
- Modify: `backend/app/api/schemas.py` (`AnalyzeRepoRequest` 832)
- Modify: `backend/tests/test_llm_user_fallback.py` (append stacks section)
- Modify: `backend/tests/test_llm_cache.py` (`test_stacks_invalid_payload_is_not_cached` 312-334)
- Modify: `backend/tests/test_stack_repo_analysis.py` (direct `_generate_services` tests 301-362)
- Modify: `backend/tests/test_stacks_llm_eval.py` (`test_pipeline_stubbed_llm_merges_env_fallback` 296-328)

**Interfaces:**
- Consumes: `resolve_llm_config_for_user` (Task 1), `generate_json(config=...)` (Task 3), `LlmConfig`/`resolve_llm_config` (Task 1).
- Produces:
  - `analyze_repo_stack(image_builder, *, git_url, git_branch, access_token, session: AsyncSession | None = None, user_id: uuid.UUID | None = None, use_server_default: bool = False) -> RepoStackAnalysis` — resolves config via `resolve_llm_config_for_user` only on the LLM path (after the manifest early-return), passes it to `_generate_services`.
  - `_generate_services(..., config: LlmConfig | None = None)` — `None` → `resolve_llm_config()`; still `None` → `LlmNotConfiguredError("AI analysis is not configured on this server.")` (keeps the 503 for unconfigured servers); cache version becomes `f"{STACKS_PROMPT_VERSION}:{config.provider}:{config.model}"`; passes `config=config` to `generate_json`.
  - `AnalyzeRepoRequest.use_server_default: bool = False`.
- Notes: `LlmProviderError` is a distinct class — it is not caught by `_generate_services`' `except LlmCallError` (which wraps `_payload_to_services` only), so it propagates before `store_cached` → cache untouched → 502 handler with `fallback_available`. `test_analyze_repo_no_manifest_without_llm_returns_503` (~line 238) is unchanged: no user row + no env → config `None` → 503 "not configured".

- [ ] **Step 1: Append the failing stacks tests**

Append to `backend/tests/test_llm_user_fallback.py`. First extend the import block at the top (the file already imports `asyncio`, `Path`, `pytest`, `LlmProviderError`, `git_source_analysis`, `user_config`, `LlmConfig`, `User`, `DefaultImageBuilder`):

```python
from app.core.exceptions import LlmNotConfiguredError
from app.core.llm import cache as cache_module
from app.core.stacks import repo_analysis
```

Then append this section (reuses the file's `_clean_llm_env` autouse fixture, `USER_CONFIG`, and `_StubBuilder` from the git section):

```python
# ---------------------------------------------------------------------------
# Stack repo-analysis section
# ---------------------------------------------------------------------------

STACKS_PAYLOAD = {
    "services": [
        {
            "service_name": "web",
            "source_kind": "git",
            "source_ref": "",
            "container_port": 8000,
            "env_var_entries": [],
            "command": None,
            "public_route": True,
            "depends_on": None,
        },
        {
            "service_name": "db",
            "source_kind": "image",
            "source_ref": "postgres:16",
            "container_port": 5432,
            "env_var_entries": [],
            "command": None,
            "public_route": False,
            "depends_on": None,
        },
    ],
    "summary_hint": "web + db",
}


def _record_stacks_fake(record: dict):
    async def fake_generate_json(
        *, prompt: str, schema: dict, config: LlmConfig | None = None
    ) -> dict:
        record["config"] = config
        return dict(STACKS_PAYLOAD)

    return fake_generate_json


def _call_generate_services(root: Path, config: LlmConfig | None = None):
    return asyncio.run(
        repo_analysis._generate_services(
            context="",
            manifest=None,
            git_url="https://github.com/o/r.git",
            git_branch="main",
            warnings=[],
            root=root,
            commit="abc123",
            config=config,
        )
    )


def test_generate_services_without_config_or_env_raises_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _no_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("generate_json must not run without a config")

    monkeypatch.setattr(repo_analysis, "generate_json", _no_call)
    with pytest.raises(LlmNotConfiguredError, match="not configured"):
        _call_generate_services(tmp_path)


def test_generate_services_uses_explicit_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_LLM_CACHE_DIR", str(tmp_path))
    record: dict = {}
    monkeypatch.setattr(repo_analysis, "generate_json", _record_stacks_fake(record))
    services, summary = _call_generate_services(tmp_path, config=USER_CONFIG)
    assert record["config"] is USER_CONFIG
    assert [service.service_name for service in services] == ["web", "db"]
    assert summary == "web + db"


def test_generate_services_user_provider_error_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VELA_LLM_CACHE_DIR", str(tmp_path))

    def _boom(*, prompt: str, schema: dict, config: LlmConfig | None = None) -> dict:
        raise LlmProviderError(
            "Could not complete AI analysis. Try again later.",
            fallback_available=True,
        )

    monkeypatch.setattr(repo_analysis, "generate_json", _boom)
    with pytest.raises(LlmProviderError):
        _call_generate_services(tmp_path, config=USER_CONFIG)
    assert (
        asyncio.run(
            cache_module.load_cached(
                "stacks",
                "abc123",
                f"{repo_analysis.STACKS_PROMPT_VERSION}:gemini:user-model",
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_analyze_repo_stack_prefers_user_row_over_env(
    db_session_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("VELA_LLM_CACHE_DIR", str(tmp_path))
    record: dict = {}
    monkeypatch.setattr(repo_analysis, "generate_json", _record_stacks_fake(record))
    async with db_session_factory() as session:
        user = User(email="stacks@example.com")
        session.add(user)
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="user-model",
            api_key="sk-user",
        )
        analysis = await repo_analysis.analyze_repo_stack(
            _StubBuilder(tmp_path),
            git_url="https://github.com/o/r.git",
            git_branch="main",
            access_token=None,
            session=session,
            user_id=user.id,
        )
    assert analysis.manifest_kind == "llm"
    assert record["config"] is not None
    assert record["config"].origin == "user"
    assert record["config"].model == "user-model"


@pytest.mark.asyncio
async def test_analyze_repo_stack_use_server_default_skips_user_row(
    db_session_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VELA_GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("VELA_LLM_CACHE_DIR", str(tmp_path))
    record: dict = {}
    monkeypatch.setattr(repo_analysis, "generate_json", _record_stacks_fake(record))
    async with db_session_factory() as session:
        user = User(email="stacks-force@example.com")
        session.add(user)
        await session.commit()
        await user_config.set_user_llm_provider(
            session,
            user.id,
            provider="gemini",
            base_url=None,
            model="user-model",
            api_key="sk-user",
        )
        await repo_analysis.analyze_repo_stack(
            _StubBuilder(tmp_path),
            git_url="https://github.com/o/r.git",
            git_branch="main",
            access_token=None,
            session=session,
            user_id=user.id,
            use_server_default=True,
        )
    assert record["config"] is not None
    assert record["config"].origin == "server"
    assert record["config"].model == "gemini-3.5-flash"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_llm_user_fallback.py -q`
Expected: the 5 new stacks tests FAIL (`_generate_services` has no `config` parameter; `analyze_repo_stack` has no `session`/`user_id`/`use_server_default` — `TypeError`); the 5 git tests still pass.

- [ ] **Step 3: Implement**

**`backend/app/core/stacks/repo_analysis.py`** — three edits:

1. Imports — add `import uuid` to the stdlib block (after `import asyncio`); change the exceptions import to `from app.core.exceptions import LlmCallError, LlmNotConfiguredError, ManifestParseError`; add `from sqlalchemy.ext.asyncio import AsyncSession` (after the pydantic import); add these two lines after `from app.core.llm import generate_json`:

```python
from app.core.llm.provider import LlmConfig, resolve_llm_config
from app.core.llm.user_config import resolve_llm_config_for_user
```

2. `_generate_services` — add `config: LlmConfig | None = None` as the last keyword parameter, and insert this right after the "Detected facts" prompt block (before `payload = await load_cached(...)`):

```python
    if config is None:
        config = resolve_llm_config()
    if config is None:
        raise LlmNotConfiguredError("AI analysis is not configured on this server.")
    cache_version = f"{STACKS_PROMPT_VERSION}:{config.provider}:{config.model}"
```

Then replace the three bare `STACKS_PROMPT_VERSION` cache arguments (`load_cached`, `store_cached`, `delete_cached`) with `cache_version`, and change the generation call to `payload = await generate_json(prompt=prompt, schema=_generation_schema(), config=config)`.

3. `analyze_repo_stack` — new signature:

```python
async def analyze_repo_stack(
    image_builder: DefaultImageBuilder,
    *,
    git_url: str,
    git_branch: str,
    access_token: str | None,
    session: AsyncSession | None = None,
    user_id: uuid.UUID | None = None,
    use_server_default: bool = False,
) -> RepoStackAnalysis:
```

On the LLM path (after `commit = await asyncio.to_thread(head_commit, root) or ""`, before the `_generate_services(...)` call) add:

```python
        config = await resolve_llm_config_for_user(
            session, user_id, force_server_default=use_server_default
        )
```

and pass `config=config` to `_generate_services(...)`. (The manifest early-return paths never resolve a config — no wasted DB query.)

**`backend/app/api/routes/stacks.py`** — in `analyze_repo_route`, extend the call:

```python
    analysis = await analyze_repo_stack(
        image_builder,
        git_url=body.git_url,
        git_branch=body.git_branch,
        access_token=access_token,
        session=session,
        user_id=current_user.id,
        use_server_default=body.use_server_default,
    )
```

**`backend/app/api/schemas.py`** — extend `AnalyzeRepoRequest`:

```python
class AnalyzeRepoRequest(BaseModel):
    git_url: str = Field(min_length=1, max_length=2048)
    git_branch: str = Field(default="main", max_length=256)
    use_server_default: bool = False
```

**Existing test updates** (direct `_generate_services` calls now hit "not configured" before the fake unless a config resolves; fakes must accept `config`):

- `backend/tests/test_llm_cache.py`:
  - Add `LlmConfig` to the imports (new line `from app.core.llm.provider import LlmConfig`).
  - `test_stacks_invalid_payload_is_not_cached`: add `monkeypatch.setenv("VELA_GEMINI_API_KEY", "test-key")` next to the monkeypatch; extend `bad_generate_json` with `config: LlmConfig | None = None`; change the final assertion's version argument to `f"{repo_analysis.STACKS_PROMPT_VERSION}:gemini:gemini-3.5-flash"`.
- `backend/tests/test_stack_repo_analysis.py`:
  - Add `from app.core.llm.provider import LlmConfig` to the imports.
  - `test_generate_services_prompt_contains_detected_facts` and `test_generate_services_prompt_redacts_git_url_credentials`: each gains `monkeypatch.setenv("VELA_GEMINI_API_KEY", "test-key")` and its `fake_generate_json` gains `config: LlmConfig | None = None`.
- `backend/tests/test_stacks_llm_eval.py`:
  - Change the provider import to `from app.core.llm.provider import LlmConfig, resolve_llm_config`.
  - `test_pipeline_stubbed_llm_merges_env_fallback`: add `monkeypatch.setenv("VELA_GEMINI_API_KEY", "test-key")` and extend `fake_generate_json` with `config: LlmConfig | None = None`.

- [ ] **Step 4: Run tests and verify green**

Run: `cd backend && python -m pytest tests -q`
Expected: ALL pass (stacks flow honors the user row; 503 unconfigured path, manifest paths, and cache tests unchanged).

- [ ] **Step 5: Lint and typecheck**

Run: `cd backend && ruff check . && mypy app/ tests/`
Expected: clean.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/stacks/repo_analysis.py backend/app/api/routes/stacks.py backend/app/api/schemas.py backend/tests/test_llm_user_fallback.py backend/tests/test_llm_cache.py backend/tests/test_stack_repo_analysis.py backend/tests/test_stacks_llm_eval.py
git commit -m "feat: stack repo analysis uses the user's LLM provider with one-click default retry"
```

---

## Task 6: Provider management routes (get/put/delete/test + `gemini-status` user info)

**Files:**
- Modify: `backend/app/api/schemas.py` (new LLM schemas before `GeminiConfigStatus` at 455; `GeminiConfigStatus` gains `user_provider`)
- Modify: `backend/app/api/routes/settings.py` (imports 5-29; replace `gemini_config_status` 55-60; new routes after it)
- Test: `backend/tests/test_llm_provider_routes.py`

**Interfaces:**
- Consumes: `user_config` service (Task 1), `config_from_parts` (Task 1), `get_provider` (Task 2), `LlmCallError`/`LlmProviderConfigError` (Task 1; the 400/502 handlers for them were added in Task 3), `UserLlmProvider` (Task 1).
- Produces (all mounted under `/api/settings`, authed):
  - `GET /api/settings/llm-provider` → `LlmProviderGet | None` (null when the user has no row).
  - `PUT /api/settings/llm-provider` (body `LlmProviderSet`) → `LlmProviderGet`. `api_key` omitted/`None` on an existing row keeps the stored key; absent + no row → 400 `LlmProviderConfigError("API key required.")` via the Task 3 handler.
  - `DELETE /api/settings/llm-provider` → 204.
  - `POST /api/settings/llm-provider/test` (body `LlmProviderTestRequest`) → `LlmProviderTestResponse`. Builds the config via `config_from_parts` (invalid parts → 400 via Task 3 handler), runs `get_provider(config).verify(config)`; `LlmCallError` → 400 with a mapped message from `exc.__cause__` (HTTP 401/403 → `Invalid API key.`; other HTTP status → `The provider rejected the request.`; connect/read/pool timeout or connect error → `Endpoint unreachable. Check the base URL and API key.`; anything else → `Could not reach the provider. Try again.`).
  - `GET /api/settings/gemini-status` → `GeminiConfigStatus(configured=…, user_provider=…)` — `configured` is true when the server env OR the user row exists.
  - Schemas: `LlmProviderKind = Literal["openai_compatible", "gemini", "anthropic"]`; `LlmProviderGet(provider, base_url=None, model, has_key=True)`; `LlmProviderSet(provider, base_url=None (max 1024), model (1..255), api_key=None (1..2048))` with a `field_validator("base_url")`: non-openai providers force `None`, openai requires an `http(s)://` URL and returns it rstrip("/")-ed; `LlmProviderTestRequest(provider, base_url=None, model (1..255, required — the UI pre-fills defaults), api_key (1..2048, required))`; `LlmProviderTestResponse(ok=True, models=None)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_llm_provider_routes.py`:

```python
"""Per-user LLM provider settings routes."""
from __future__ import annotations

import httpx
import pytest

from app.api.routes import settings as settings_routes
from app.core.exceptions import LlmCallError

_LLM_VARS = (
    "VELA_VERTEX_API_KEY",
    "VELA_VERTEX_PROJECT_ID",
    "VELA_VERTEX_LOCATION",
    "VELA_VERTEX_MODEL",
    "VELA_GEMINI_API_KEY",
    "VELA_GEMINI_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _LLM_VARS:
        monkeypatch.delenv(name, raising=False)


class _StubProvider:
    def __init__(
        self, models: list[str] | None = None, error: Exception | None = None
    ) -> None:
        self.models = models
        self.error = error

    async def verify(self, config: object) -> list[str] | None:
        if self.error is not None:
            raise self.error
        return self.models


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: _StubProvider) -> None:
    monkeypatch.setattr(settings_routes, "get_provider", lambda config: provider)


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://provider.test/models")
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(status_code, request=request)
    )


def test_get_llm_provider_empty(api_client) -> None:
    api_client.delete("/api/settings/llm-provider")
    response = api_client.get("/api/settings/llm-provider")
    assert response.status_code == 200
    assert response.json() is None


def test_put_and_get_llm_provider_roundtrip(api_client) -> None:
    response = api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "gemini-2.5-flash", "api_key": "sk-test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "provider": "gemini",
        "base_url": None,
        "model": "gemini-2.5-flash",
        "has_key": True,
    }
    again = api_client.get("/api/settings/llm-provider")
    assert again.status_code == 200
    assert again.json() == body


def test_put_llm_provider_without_key_when_absent_returns_400(api_client) -> None:
    api_client.delete("/api/settings/llm-provider")
    response = api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "gemini-2.5-flash"},
    )
    assert response.status_code == 400
    assert "API key required" in response.json()["detail"]


def test_put_llm_provider_blank_key_keeps_existing(api_client) -> None:
    api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "old-model", "api_key": "sk-old"},
    )
    response = api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "new-model"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "new-model"
    assert body["has_key"] is True


def test_put_openai_compatible_requires_base_url(api_client) -> None:
    response = api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "openai_compatible", "model": "gpt-4o-mini", "api_key": "k"},
    )
    assert response.status_code == 422


def test_put_openai_compatible_stores_base_url(api_client) -> None:
    response = api_client.put(
        "/api/settings/llm-provider",
        json={
            "provider": "openai_compatible",
            "base_url": "https://openrouter.ai/api/v1/",
            "model": "gpt-4o-mini",
            "api_key": "k",
        },
    )
    assert response.status_code == 200
    assert response.json()["base_url"] == "https://openrouter.ai/api/v1"


def test_put_non_openai_drops_base_url(api_client) -> None:
    response = api_client.put(
        "/api/settings/llm-provider",
        json={
            "provider": "anthropic",
            "base_url": "https://ignored.example/v1",
            "model": "claude-sonnet-4-5",
            "api_key": "k",
        },
    )
    assert response.status_code == 200
    assert response.json()["base_url"] is None


def test_delete_llm_provider(api_client) -> None:
    api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    response = api_client.delete("/api/settings/llm-provider")
    assert response.status_code == 204
    assert api_client.get("/api/settings/llm-provider").json() is None


def test_test_llm_provider_success(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_provider(monkeypatch, _StubProvider(models=["m1", "m2"]))
    response = api_client.post(
        "/api/settings/llm-provider/test",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "models": ["m1", "m2"]}


def test_test_llm_provider_invalid_key_returns_400(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = LlmCallError("Could not reach the provider.")
    error.__cause__ = _status_error(401)
    _use_provider(monkeypatch, _StubProvider(error=error))
    response = api_client.post(
        "/api/settings/llm-provider/test",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid API key."


def test_test_llm_provider_rejected_returns_400(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = LlmCallError("Could not reach the provider.")
    error.__cause__ = _status_error(400)
    _use_provider(monkeypatch, _StubProvider(error=error))
    response = api_client.post(
        "/api/settings/llm-provider/test",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "The provider rejected the request."


def test_test_llm_provider_unreachable_returns_400(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = LlmCallError("Could not reach the provider.")
    error.__cause__ = httpx.ConnectError("no route")
    _use_provider(monkeypatch, _StubProvider(error=error))
    response = api_client.post(
        "/api/settings/llm-provider/test",
        json={"provider": "gemini", "model": "m", "api_key": "k"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Endpoint unreachable. Check the base URL and API key."
    )


def test_gemini_status_reports_user_provider(api_client) -> None:
    api_client.put(
        "/api/settings/llm-provider",
        json={"provider": "anthropic", "model": "claude-sonnet-4-5", "api_key": "k"},
    )
    response = api_client.get("/api/settings/gemini-status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["user_provider"]["provider"] == "anthropic"
    assert body["user_provider"]["has_key"] is True


def test_gemini_status_unconfigured(api_client) -> None:
    api_client.delete("/api/settings/llm-provider")
    response = api_client.get("/api/settings/gemini-status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["user_provider"] is None
```

Note: `test_gemini_status_reports_user_provider` depends on the `_clean_llm_env` autouse fixture (no server LLM) so `configured` proves the user row counts.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_llm_provider_routes.py -q`
Expected: FAIL — 404 on all `/llm-provider` routes; `gemini-status` response lacks `user_provider` (assertion error).

- [ ] **Step 3: Implement**

**`backend/app/api/schemas.py`** — add `ValidationInfo` to the pydantic import block, then insert before `class GeminiConfigStatus` and extend it:

```python
LlmProviderKind = Literal["openai_compatible", "gemini", "anthropic"]


class LlmProviderGet(BaseModel):
    provider: LlmProviderKind
    base_url: str | None = None
    model: str
    has_key: bool = True


class LlmProviderSet(BaseModel):
    provider: LlmProviderKind
    base_url: str | None = Field(default=None, max_length=1024)
    model: str = Field(min_length=1, max_length=255)
    api_key: str | None = Field(default=None, min_length=1, max_length=2048)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        provider = info.data.get("provider")
        if provider != "openai_compatible":
            return None
        if not value:
            raise ValueError("Base URL is required for OpenAI-compatible providers.")
        root = value.rstrip("/")
        if not root.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://.")
        return root


class LlmProviderTestRequest(BaseModel):
    provider: LlmProviderKind
    base_url: str | None = Field(default=None, max_length=1024)
    model: str = Field(min_length=1, max_length=255)
    api_key: str = Field(min_length=1, max_length=2048)


class LlmProviderTestResponse(BaseModel):
    ok: bool = True
    models: list[str] | None = None


class GeminiConfigStatus(BaseModel):
    configured: bool
    user_provider: LlmProviderGet | None = None
```

**`backend/app/api/routes/settings.py`** — rewrite the import block and replace `gemini_config_status`, then insert the new routes after it. New imports:

```python
"""User settings (AI pre-fill, LLM provider, and email notifications)."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    AiPrefillPreferences,
    AiPrefillPreferencesUpdate,
    AlertHistoryEntry,
    ContainerMonitoringStatus,
    EmailNotificationPreferences,
    EmailNotificationPreferencesUpdate,
    GeminiConfigStatus,
    LlmProviderGet,
    LlmProviderSet,
    LlmProviderTestRequest,
    LlmProviderTestResponse,
)
from app.core import user_preferences
from app.core.exceptions import LlmCallError
from app.core.llm import resolve_llm_config
from app.core.llm.registry import get_provider
from app.core.llm.user_config import (
    config_from_parts,
    delete_user_llm_provider,
    get_user_llm_provider,
    set_user_llm_provider,
)
```

(keep the remaining existing imports — `DEFAULT_ALERT_FREQUENCY`/`DEFAULT_ALERT_TYPES`, the `container_monitor` block, `from app.db.models import AlertHistory, EmailPreference, User, UserLlmProvider`) and add these helpers after `router = APIRouter()`:

```python
def _provider_to_get(row: UserLlmProvider) -> LlmProviderGet:
    return LlmProviderGet(
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        has_key=row.api_key_encrypted is not None,
    )


def _llm_test_failure_message(exc: LlmCallError) -> str:
    cause = exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        if cause.response.status_code in (401, 403):
            return "Invalid API key."
        return "The provider rejected the request."
    if isinstance(
        cause,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.PoolTimeout,
        ),
    ):
        return "Endpoint unreachable. Check the base URL and API key."
    return "Could not reach the provider. Try again."
```

Replace `gemini_config_status` (lines 55-60) with:

```python
@router.get("/gemini-status", response_model=GeminiConfigStatus)
async def gemini_config_status(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GeminiConfigStatus:
    row = await get_user_llm_provider(session, current_user.id)
    return GeminiConfigStatus(
        configured=resolve_llm_config() is not None or row is not None,
        user_provider=_provider_to_get(row) if row is not None else None,
    )
```

Insert after it:

```python
@router.get("/llm-provider", response_model=LlmProviderGet | None)
async def get_llm_provider(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> LlmProviderGet | None:
    row = await get_user_llm_provider(session, current_user.id)
    return _provider_to_get(row) if row is not None else None


@router.put("/llm-provider", response_model=LlmProviderGet)
async def put_llm_provider(
    body: LlmProviderSet,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> LlmProviderGet:
    row = await set_user_llm_provider(
        session,
        current_user.id,
        provider=body.provider,
        base_url=body.base_url,
        model=body.model,
        api_key=body.api_key,
    )
    return _provider_to_get(row)


@router.delete("/llm-provider", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_provider(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await delete_user_llm_provider(session, current_user.id)


@router.post("/llm-provider/test", response_model=LlmProviderTestResponse)
async def test_llm_provider_route(
    body: LlmProviderTestRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> LlmProviderTestResponse:
    config = config_from_parts(
        provider=body.provider,
        base_url=body.base_url,
        model=body.model,
        api_key=body.api_key,
    )
    try:
        models = await get_provider(config).verify(config)
    except LlmCallError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_llm_test_failure_message(exc),
        ) from exc
    return LlmProviderTestResponse(ok=True, models=models)
```

- [ ] **Step 4: Run tests and verify green**

Run: `cd backend && python -m pytest tests -q`
Expected: ALL pass.

- [ ] **Step 5: Lint and typecheck**

Run: `cd backend && ruff check . && mypy app/ tests/`
Expected: clean.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/api/schemas.py backend/app/api/routes/settings.py backend/tests/test_llm_provider_routes.py
git commit -m "feat: per-user LLM provider settings routes with connection test"
```

---

## Task 7: Frontend API layer for the LLM provider

**Files:**
- Modify: `frontend/src/api/settings.ts` (whole file, 28 lines today)
- Create: `frontend/src/api/llmErrors.ts`
- Modify: `frontend/src/api/client.ts` (re-exports)
- Modify: `frontend/src/api/builds.ts` (`analyzeGitSource` 39-47)
- Modify: `frontend/src/api/stacks.ts` (`analyzeRepo` 99-104)

**Interfaces:**
- Consumes: `apiGet`/`apiPut`/`apiDelete`/`apiPost`/`ApiError` (`./core`). `ApiError.body` is the raw response **string** — `isLlmFallbackError` parses it.
- Produces:
  - `settings.ts`: `LlmProviderKind = 'openai_compatible' | 'gemini' | 'anthropic'`; `LlmProviderConfig { provider, base_url: string | null, model, has_key }`; `LlmProviderUpdate { provider, base_url?, model, api_key? }`; `LlmProviderTestRequest { provider, base_url?, model, api_key }`; `LlmProviderTestResult { ok: boolean, models: string[] | null }`; `GeminiConfigStatus { configured, user_provider: LlmProviderConfig | null }`; fns `getLlmProvider(): Promise<LlmProviderConfig | null>`, `putLlmProvider(update): Promise<LlmProviderConfig>`, `deleteLlmProvider(): Promise<void>`, `testLlmProvider(request): Promise<LlmProviderTestResult>`; `getGeminiConfigStatus()` now returns `Promise<GeminiConfigStatus>` (superset of today's `{configured}`).
  - `llmErrors.ts`: `isLlmFallbackError(error: unknown): boolean` — `error instanceof ApiError` and parsed body has `fallback_available === true`.
  - `client.ts` re-exports all of the above.
  - `analyzeGitSource`/`analyzeRepo` bodies gain `use_server_default?: boolean` (absent/undefined keys are dropped by `JSON.stringify` — no behavior change for existing callers).

- [ ] **Step 1: Implement**

**`frontend/src/api/settings.ts`** — replace the whole file:

```ts
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './core'

export type AiPrefillPreferences = {
  git_branch: boolean
  container_port: boolean
  container_name: boolean
  env_vars: boolean
  start_command: boolean
}

export type AiPrefillPreferencesUpdate = Partial<AiPrefillPreferences>

export async function getAiPrefillPreferences(): Promise<AiPrefillPreferences> {
  return apiGet<AiPrefillPreferences>('/api/settings/ai-prefill')
}

export async function patchAiPrefillPreferences(
  patch: AiPrefillPreferencesUpdate
): Promise<AiPrefillPreferences> {
  return apiPatch<AiPrefillPreferences, AiPrefillPreferencesUpdate>(
    '/api/settings/ai-prefill',
    patch
  )
}

export type LlmProviderKind = 'openai_compatible' | 'gemini' | 'anthropic'

export type LlmProviderConfig = {
  provider: LlmProviderKind
  base_url: string | null
  model: string
  has_key: boolean
}

export type LlmProviderUpdate = {
  provider: LlmProviderKind
  base_url?: string | null
  model: string
  api_key?: string | null
}

export type LlmProviderTestRequest = {
  provider: LlmProviderKind
  base_url?: string | null
  model: string
  api_key: string
}

export type LlmProviderTestResult = {
  ok: boolean
  models: string[] | null
}

export type GeminiConfigStatus = {
  configured: boolean
  user_provider: LlmProviderConfig | null
}

export async function getGeminiConfigStatus(): Promise<GeminiConfigStatus> {
  return apiGet<GeminiConfigStatus>('/api/settings/gemini-status')
}

export async function getLlmProvider(): Promise<LlmProviderConfig | null> {
  return apiGet<LlmProviderConfig | null>('/api/settings/llm-provider')
}

export async function putLlmProvider(
  update: LlmProviderUpdate
): Promise<LlmProviderConfig> {
  return apiPut<LlmProviderConfig, LlmProviderUpdate>(
    '/api/settings/llm-provider',
    update
  )
}

export async function deleteLlmProvider(): Promise<void> {
  await apiDelete('/api/settings/llm-provider')
}

export async function testLlmProvider(
  request: LlmProviderTestRequest
): Promise<LlmProviderTestResult> {
  return apiPost<LlmProviderTestResult, LlmProviderTestRequest>(
    '/api/settings/llm-provider/test',
    request
  )
}
```

**`frontend/src/api/llmErrors.ts`** — new file:

```ts
import { ApiError } from './core'

/**
 * True when the API reports a user-provider LLM failure while the server's
 * own provider is still usable as a one-click fallback.
 */
export function isLlmFallbackError(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return false
  }
  try {
    const parsed = JSON.parse(error.body) as { fallback_available?: unknown }
    return parsed.fallback_available === true
  } catch {
    return false
  }
}
```

**`frontend/src/api/client.ts`** — three edits:

1. Add a new value-export block (next to the other `export { ... } from` blocks):

```ts
export { isLlmFallbackError } from './llmErrors'
```

2. Replace the `./settings` value-export block with:

```ts
export {
  deleteLlmProvider,
  getAiPrefillPreferences,
  getGeminiConfigStatus,
  getLlmProvider,
  patchAiPrefillPreferences,
  putLlmProvider,
  testLlmProvider,
} from './settings'
```

3. Replace the `./settings` type-export block with:

```ts
export type {
  AiPrefillPreferences,
  AiPrefillPreferencesUpdate,
  GeminiConfigStatus,
  LlmProviderConfig,
  LlmProviderKind,
  LlmProviderTestRequest,
  LlmProviderTestResult,
  LlmProviderUpdate,
} from './settings'
```

**`frontend/src/api/builds.ts`** — extend the `analyzeGitSource` body type (lines 39-42):

```ts
export async function analyzeGitSource(body: {
  git_url: string
  git_branch: string
  use_server_default?: boolean
}): Promise<GitSourceAnalysis> {
```

**`frontend/src/api/stacks.ts`** — extend the `analyzeRepo` body type (lines 99-102):

```ts
export async function analyzeRepo(body: {
  git_url: string
  git_branch: string
  use_server_default?: boolean
}): Promise<RepoAnalysisResult> {
```

- [ ] **Step 2: Verify**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: clean (no runtime behavior change; e2e coverage lands in Task 10).

- [ ] **Step 3: Commit**

```powershell
git add frontend/src/api/settings.ts frontend/src/api/llmErrors.ts frontend/src/api/client.ts frontend/src/api/builds.ts frontend/src/api/stacks.ts
git commit -m "feat: frontend API layer for per-user LLM provider"
```

---

## Task 8: LLM provider settings card (frontend)

A single settings card where the user saves, tests, and removes their own LLM provider (BYO key) via Task 6's routes. Saving or removing bumps a `refreshKey` that makes `AiPrefillSettingsCard` re-fetch the server status.

**Files:**
- Create: `frontend/src/pages/settings/LlmProviderCard.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx` (import, `aiStatusVersion` state, render above `AiPrefillSettingsCard`, `refreshKey` prop + effect dep)

**Interfaces:**
- Consumes (all from `'../../api/client'`, added in Task 7): `getLlmProvider(): Promise<LlmProviderConfig | null>`, `putLlmProvider(update: LlmProviderUpdate): Promise<LlmProviderConfig>`, `deleteLlmProvider(): Promise<void>`, `testLlmProvider(request: LlmProviderTestRequest): Promise<LlmProviderTestResult>`, `getGeminiConfigStatus(): Promise<GeminiConfigStatus>`, `formatApiError`; type `LlmProviderKind` (the other Task 7 types flow through the function signatures).
- Consumes: `ConfirmDialog` from `frontend/src/components/ConfirmDialog.tsx` (props `open, title, message, confirmLabel, cancelLabel, busy, onConfirm, onClose`); existing CSS `settings-card*` plus `settings-form` / `settings-form__field` / `settings-form__label` / `settings-form__input` (defined in `frontend/src/index.css:1142-1213`, already used by `AuditLogPage.tsx`, `LogsPage.tsx`, `EmailNotificationSettings.tsx`).

- [ ] **Step 1: Create `frontend/src/pages/settings/LlmProviderCard.tsx`**

**`frontend/src/pages/settings/LlmProviderCard.tsx`** — new file:

```tsx
import { useEffect, useState } from 'react'
import {
  deleteLlmProvider,
  formatApiError,
  getGeminiConfigStatus,
  getLlmProvider,
  putLlmProvider,
  testLlmProvider,
  type LlmProviderKind,
} from '../../api/client'
import ConfirmDialog from '../../components/ConfirmDialog'

const PROVIDER_LABELS: Record<LlmProviderKind, string> = {
  openai_compatible: 'OpenAI-compatible',
  gemini: 'Gemini',
  anthropic: 'Anthropic',
}

const PROVIDER_DEFAULTS: Record<
  LlmProviderKind,
  { baseUrl: string; model: string }
> = {
  openai_compatible: { baseUrl: 'https://api.openai.com/v1', model: '' },
  gemini: { baseUrl: '', model: 'gemini-3.5-flash' },
  anthropic: { baseUrl: '', model: 'claude-sonnet-4-5' },
}

const CUSTOM_MODEL_VALUE = '__custom__'

type LlmProviderCardProps = {
  onChanged?: () => void
}

export default function LlmProviderCard({ onChanged }: LlmProviderCardProps) {
  const [provider, setProvider] = useState<LlmProviderKind>('openai_compatible')
  const [baseUrl, setBaseUrl] = useState('https://api.openai.com/v1')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [modelOptions, setModelOptions] = useState<string[] | null>(null)
  const [hasSavedRow, setHasSavedRow] = useState(false)
  const [savedHasKey, setSavedHasKey] = useState(false)
  const [serverConfigured, setServerConfigured] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<'test' | 'save' | 'remove' | null>(null)
  const [message, setMessage] = useState<
    { tone: 'ok' | 'err'; text: string } | null
  >(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    void Promise.allSettled([
      getLlmProvider(),
      getGeminiConfigStatus(),
    ]).then(([providerResult, statusResult]) => {
      if (cancelled) {
        return
      }
      if (providerResult.status === 'fulfilled') {
        const row = providerResult.value
        if (row) {
          setProvider(row.provider)
          setBaseUrl(row.base_url ?? PROVIDER_DEFAULTS[row.provider].baseUrl)
          setModel(row.model)
          setSavedHasKey(row.has_key)
          setHasSavedRow(true)
        }
      } else {
        setLoadError(formatApiError(providerResult.reason))
      }
      if (statusResult.status === 'fulfilled') {
        setServerConfigured(statusResult.value.configured)
      }
    }).finally(() => {
      if (!cancelled) {
        setLoading(false)
      }
    })
    return () => {
      cancelled = true
    }
  }, [])

  const effectiveModel = model.trim()
  const canTest =
    !loading &&
    busy === null &&
    apiKey.trim() !== '' &&
    effectiveModel !== '' &&
    (provider !== 'openai_compatible' || baseUrl.trim() !== '')
  const canSave =
    !loading &&
    busy === null &&
    effectiveModel !== '' &&
    (provider !== 'openai_compatible' || baseUrl.trim() !== '')

  function handleProviderChange(next: LlmProviderKind) {
    setProvider(next)
    setBaseUrl(PROVIDER_DEFAULTS[next].baseUrl)
    setModel(PROVIDER_DEFAULTS[next].model)
    setModelOptions(null)
    setMessage(null)
  }

  async function handleTest() {
    setBusy('test')
    setMessage(null)
    try {
      const result = await testLlmProvider({
        provider,
        base_url:
          provider === 'openai_compatible' ? baseUrl.trim() || null : null,
        api_key: apiKey.trim(),
        model: effectiveModel,
      })
      setModelOptions(result.models ?? [])
      setMessage({ tone: 'ok', text: 'Provider reachable.' })
    } catch (error) {
      setMessage({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(null)
    }
  }

  async function handleSave() {
    setBusy('save')
    setMessage(null)
    try {
      await putLlmProvider({
        provider,
        base_url:
          provider === 'openai_compatible' ? baseUrl.trim() || null : null,
        model: effectiveModel,
        api_key: apiKey.trim() || undefined,
      })
      const updated = await getLlmProvider()
      setSavedHasKey(Boolean(updated?.has_key))
      setHasSavedRow(true)
      setMessage({ tone: 'ok', text: 'LLM provider saved.' })
      onChanged?.()
    } catch (error) {
      setMessage({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(null)
    }
  }

  async function handleRemoveConfirm() {
    setBusy('remove')
    setMessage(null)
    try {
      await deleteLlmProvider()
      setProvider('openai_compatible')
      setBaseUrl(PROVIDER_DEFAULTS.openai_compatible.baseUrl)
      setModel(PROVIDER_DEFAULTS.openai_compatible.model)
      setApiKey('')
      setModelOptions(null)
      setHasSavedRow(false)
      setSavedHasKey(false)
      setMessage({ tone: 'ok', text: 'LLM provider removed.' })
      setConfirmRemoveOpen(false)
      onChanged?.()
    } catch (error) {
      setMessage({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <div>
          <h3 className="settings-card__title">LLM provider</h3>
          <p className="settings-card__subtitle">
            Bring your own key. Your provider overrides the server default
            when set.
          </p>
        </div>
      </div>
      <div className="settings-card__body">
        {loading ? (
          <p className="settings-card__muted">Loading…</p>
        ) : (
          <>
            {hasSavedRow ? (
              <p className="settings-card__muted">
                Your key is active — it overrides the server default.
              </p>
            ) : serverConfigured === true ? (
              <p className="settings-card__muted">
                Server default is configured. Add your own key to take
                priority.
              </p>
            ) : serverConfigured === false ? (
              <p className="settings-card__muted">
                No AI provider is configured yet.
              </p>
            ) : null}
            {loadError ? (
              <p className="settings-banner settings-banner--err" role="alert">
                {loadError}
              </p>
            ) : null}
            {message ? (
              <p
                className={
                  message.tone === 'ok'
                    ? 'settings-banner settings-banner--ok'
                    : 'settings-banner settings-banner--err'
                }
                role={message.tone === 'err' ? 'alert' : 'status'}
              >
                {message.text}
              </p>
            ) : null}
            <div className="settings-form">
              <div className="settings-form__field">
                <label className="settings-form__label" htmlFor="llm-provider">
                  Provider
                </label>
                <select
                  id="llm-provider"
                  className="settings-form__input"
                  value={provider}
                  disabled={loading || busy !== null}
                  onChange={(event) =>
                    handleProviderChange(event.target.value as LlmProviderKind)
                  }
                >
                  {(Object.keys(PROVIDER_LABELS) as LlmProviderKind[]).map(
                    (kind) => (
                      <option key={kind} value={kind}>
                        {PROVIDER_LABELS[kind]}
                      </option>
                    )
                  )}
                </select>
              </div>
              {provider === 'openai_compatible' ? (
                <div className="settings-form__field">
                  <label className="settings-form__label" htmlFor="llm-base-url">
                    Base URL
                  </label>
                  <input
                    id="llm-base-url"
                    className="settings-form__input"
                    value={baseUrl}
                    disabled={loading || busy !== null}
                    onChange={(event) => setBaseUrl(event.target.value)}
                  />
                </div>
              ) : null}
              <div className="settings-form__field">
                <label className="settings-form__label" htmlFor="llm-api-key">
                  API key
                </label>
                <input
                  id="llm-api-key"
                  className="settings-form__input"
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  disabled={loading || busy !== null}
                  placeholder={
                    savedHasKey ? 'Saved — leave blank to keep' : 'sk-…'
                  }
                  onChange={(event) => setApiKey(event.target.value)}
                />
              </div>

              <div className="settings-form__field">
                <label className="settings-form__label" htmlFor="llm-model">
                  Model
                </label>
                {modelOptions !== null ? (
                  <>
                    <select
                      id="llm-model"
                      className="settings-form__input"
                      value={
                        modelOptions.includes(model) ? model : CUSTOM_MODEL_VALUE
                      }
                      disabled={loading || busy !== null}
                      onChange={(event) => {
                        const value = event.target.value
                        if (value !== CUSTOM_MODEL_VALUE) {
                          setModel(value)
                        }
                      }}
                    >
                      {modelOptions.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                      <option value={CUSTOM_MODEL_VALUE}>Custom…</option>
                    </select>
                    {modelOptions.includes(model) ? null : (
                      <input
                        className="settings-form__input"
                        value={model}
                        disabled={loading || busy !== null}
                        aria-label="Custom model name"
                        onChange={(event) => setModel(event.target.value)}
                      />
                    )}
                  </>
                ) : (
                  <input
                    id="llm-model"
                    className="settings-form__input"
                    value={model}
                    disabled={loading || busy !== null}
                    placeholder={
                      PROVIDER_DEFAULTS[provider].model || 'model-name'
                    }
                    onChange={(event) => setModel(event.target.value)}
                  />
                )}
              </div>
            </div>
            <div className="settings-card__actions">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => void handleTest()}
                disabled={!canTest}
              >
                {busy === 'test' ? 'Testing…' : 'Test'}
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void handleSave()}
                disabled={!canSave}
              >
                {busy === 'save' ? 'Saving…' : 'Save'}
              </button>
              {hasSavedRow ? (
                <button
                  type="button"
                  className="btn btn--danger"
                  onClick={() => setConfirmRemoveOpen(true)}
                >
                  {busy === 'remove' ? 'Removing…' : 'Remove'}
                </button>
              ) : null}
            </div>
          </>
        )}
      </div>
      <ConfirmDialog
        open={confirmRemoveOpen}
        title="Remove LLM provider?"
        message="Your key will be deleted. AI analysis falls back to the server default."
        confirmLabel={busy === 'remove' ? 'Removing…' : 'Remove'}
        busy={busy === 'remove'}
        onConfirm={() => void handleRemoveConfirm()}
        onClose={() => setConfirmRemoveOpen(false)}
      />
    </div>
  )
}
```

- [ ] **Step 2: Wire the card into `frontend/src/pages/SettingsPage.tsx`**

Five edits, in order:

**2a.** Add the import above the existing `ProfileSection` import:

Replace:
```tsx
} from '../api/client'
import ProfileSection from './settings/ProfileSection'
```
with:
```tsx
} from '../api/client'
import LlmProviderCard from './settings/LlmProviderCard'
import ProfileSection from './settings/ProfileSection'
```

**2b.** Add the `aiStatusVersion` state after the `disconnectDialogOpen` state:

Replace:
```tsx
  const [disconnectDialogOpen, setDisconnectDialogOpen] = useState(false)
```
with:
```tsx
  const [disconnectDialogOpen, setDisconnectDialogOpen] = useState(false)
  const [aiStatusVersion, setAiStatusVersion] = useState(0)
```

**2c.** Render the card above the AI card and pass `refreshKey`:

Replace:
```tsx
      <AiPrefillSettingsCard />

      <EmailNotificationSettingsCard />
```
with:
```tsx
      <LlmProviderCard
        onChanged={() => setAiStatusVersion((version) => version + 1)}
      />

      <AiPrefillSettingsCard refreshKey={aiStatusVersion} />

      <EmailNotificationSettingsCard />
```

**2d.** Make `AiPrefillSettingsCard` accept the prop:

Replace:
```tsx
function AiPrefillSettingsCard() {
```
with:
```tsx
function AiPrefillSettingsCard({ refreshKey = 0 }: { refreshKey?: number }) {
```

**2e.** Re-run its mount effect when `refreshKey` changes (this is the only `}, [])` immediately before `async function onToggle`):

Replace:
```tsx
    return () => {
      cancelled = true
    }
  }, [])

  async function onToggle(field: keyof AiPrefillPreferences, enabled: boolean) {
```
with:
```tsx
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  async function onToggle(field: keyof AiPrefillPreferences, enabled: boolean) {
```

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

Check `git status` first; stage only these two files.

```powershell
git add frontend/src/pages/settings/LlmProviderCard.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "feat: LLM provider settings card"
```

---

## Task 9: Retry analysis with Vela default (frontend)

When the user's own LLM provider fails, the API returns 502 with `fallback_available: true` (backend Tasks 3/4/5). `isLlmFallbackError` (Task 7) detects that shape. This task adds a "Retry with Vela default" affordance on every surface that runs repo analysis — the container run form, the new-stack modal, and the stack service edit form — and threads a `useServerDefault` flag into `analyzeGitSource`/`analyzeRepo`, sending `use_server_default: true` (Task 7 already added the optional body field; the backend already accepts it).

**Files:**
- Modify: `frontend/src/pages/containers/useGitSourceAnalysis.ts`
- Modify: `frontend/src/pages/containers/useContainerRunForm.ts`
- Modify: `frontend/src/pages/containers/ContainersRunFormFields.tsx`
- Modify: `frontend/src/pages/ContainersPage.tsx`
- Modify: `frontend/src/pages/stacks/NewStackModal.tsx`
- Modify: `frontend/src/pages/stacks/ServiceEditForm.tsx`

**Interfaces:**
- Consumes (Task 7, re-exported by `frontend/src/api/client.ts`): `isLlmFallbackError(error: unknown): boolean` — import from `'../../api/client'` (all six files live under `pages/containers` or `pages/stacks`); `analyzeGitSource`/`analyzeRepo` bodies with `use_server_default?: boolean`.
- Produces: `llmFallbackAvailable` on the `useGitSourceAnalysis` return object; a "Retry with Vela default" button on the three analysis-error surfaces; a `useServerDefault` parameter on `onAnalyzeGitSource` (`useContainerRunForm`), `handleAnalyze` (`NewStackModal`) and `onAnalyzeGitSource` (`ServiceEditForm`).

- [ ] **Step 1: `frontend/src/pages/containers/useGitSourceAnalysis.ts`**

**1a. Import** — add `isLlmFallbackError` to the existing `'../../api/client'` block (lines 2-8):

```ts
import {
  analyzeGitSource,
  formatApiError,
  getAiPrefillPreferences,
  isLlmFallbackError,
  type AiPrefillPreferences,
  type GitSourceAnalysis,
} from '../../api/client'
```

**1b. State** — next to the other `useState` calls, after `analysisError` (line 24):

```ts
  const [llmFallbackAvailable, setLlmFallbackAvailable] = useState(false)
```

**1c. `clearAnalysis`** (lines 45-49) becomes:

```ts
  const clearAnalysis = useCallback(() => {
    setAnalysisLoading(false)
    setAnalysisError(null)
    setLlmFallbackAvailable(false)
    setSuccessToast(null)
  }, [])
```

**1d. `runAnalysis`** (lines 55-91) — new signature and a reset at the top (with the existing resets, lines 60-62):

```ts
  const runAnalysis = useCallback(
    async (
      gitUrl: string,
      gitBranch: string,
      useServerDefault = false,
    ): Promise<GitSourceAnalysis | null> => {
      setAnalysisLoading(true)
      setAnalysisError(null)
      setLlmFallbackAvailable(false)
      setSuccessToast(null)
      try {
```

The prefs block, `applyGitSourceAnalysis`, success toast, and `finally` are unchanged; the API call (lines 73-76) becomes:

```ts
        const analysis: GitSourceAnalysis = await analyzeGitSource({
          git_url: gitUrl,
          git_branch: gitBranch,
          use_server_default: useServerDefault,
        })
```

and the catch block (lines 83-85) becomes:

```ts
      } catch (error) {
        setLlmFallbackAvailable(isLlmFallbackError(error))
        setAnalysisError(formatApiError(error))
        return null
      }
```

The `useCallback` deps `[preferences, setters]` are unchanged (`setLlmFallbackAvailable` is stable).

**1e. Return** (lines 93-100) gains `llmFallbackAvailable,`:

```ts
  return {
    analysisLoading,
    analysisError,
    llmFallbackAvailable,
    successToast,
    dismissSuccessToast,
    runAnalysis,
    clearAnalysis,
  }
```

- [ ] **Step 2: `frontend/src/pages/containers/useContainerRunForm.ts`**

`onAnalyzeGitSource` (lines 186-201) becomes — it is already returned from the hook (line 436), no other changes:

```ts
  async function onAnalyzeGitSource(useServerDefault = false) {
    const selection = deploySource.selection
    if (selection?.kind !== 'git') {
      return
    }
    const analysis = await gitAnalysis.runAnalysis(
      selection.url,
      gitBranch.trim() || 'main',
      useServerDefault,
    )
    if (analysis?.needs_manual_build_config) {
      openBuildConfigModal({
        initial: buildOverrideFromAnalysis(analysis),
        retryOnConfirm: false,
      })
    }
  }
```

- [ ] **Step 3: `frontend/src/pages/containers/ContainersRunFormFields.tsx`**

**3a. Props type** (lines 111-117) gains two members:

```ts
type ContainersRunGitFieldsProps = ContainersRunFormFieldsProps & {
  gitBranch: string
  onGitBranchChange: (value: string) => void
  gitAnalysisLoading: boolean
  gitAnalysisError: string | null
  gitLlmFallbackAvailable: boolean
  onRetryWithDefault: () => void
  onAnalyzeGit: () => void
}
```

**3b. Destructure** (lines 119-130) gains the two new props:

```ts
export function ContainersRunGitFields({
  containerName,
  onContainerNameChange,
  containerPort,
  onContainerPortChange,
  portError,
  gitBranch,
  onGitBranchChange,
  gitAnalysisLoading,
  gitAnalysisError,
  gitLlmFallbackAvailable,
  onRetryWithDefault,
  onAnalyzeGit,
}: ContainersRunGitFieldsProps) {
```

**3c. Retry button** — after the existing error paragraph (lines 177-184), before the closing `</div>`:

```tsx
      {gitAnalysisError && gitLlmFallbackAvailable ? (
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={onRetryWithDefault}
        >
          Retry with Vela default
        </button>
      ) : null}
```

- [ ] **Step 4: `frontend/src/pages/ContainersPage.tsx`**

The `<ContainersRunGitFields ... />` render (lines 201-212) gains two props (after `gitAnalysisError`, before `onAnalyzeGit`):

```tsx
            gitLlmFallbackAvailable={gitAnalysis.llmFallbackAvailable}
            onRetryWithDefault={() => void onAnalyzeGitSource(true)}
```

- [ ] **Step 5: `frontend/src/pages/stacks/NewStackModal.tsx`**

**5a. Import** — add `isLlmFallbackError` to the existing `'../../api/client'` block (lines 5-11):

```ts
import {
  analyzeRepo,
  createStack,
  formatApiError,
  isLlmFallbackError,
  parseManifest,
  type StackServiceCreate,
} from '../../api/client'
```

**5b. State** — with the other `useState` declarations (lines 64-76), e.g. after `error`:

```ts
  const [llmFallbackAvailable, setLlmFallbackAvailable] = useState(false)
```

**5c. `handleAnalyze`** (lines 195-225) becomes:

```ts
  async function handleAnalyze(useServerDefault = false) {
    if (!sourceLooksLikeGitUrl(repoUrl)) {
      setError('Enter a Git repository URL starting with https://, http://, ssh://, or git@.')
      return
    }
    setWorking(true)
    setError(null)
    setLlmFallbackAvailable(false)
    try {
      const result = await analyzeRepo({
        git_url: repoUrl.trim(),
        git_branch: branch.trim() || 'main',
        use_server_default: useServerDefault,
      })
      if (!stackName.trim()) {
        setStackName(stackNameFromSource(repoUrl))
      }
      setServices(result.services)
      setWarnings(result.warnings)
      setOrigin(
        result.manifest_kind === 'llm'
          ? 'AI-generated — review carefully'
          : result.manifest_path
            ? `From ${result.manifest_path}`
            : originLabel(result.manifest_kind),
      )
      setStep('review')
    } catch (err) {
      setLlmFallbackAvailable(isLlmFallbackError(err))
      setError(formatApiError(err))
    } finally {
      setWorking(false)
    }
  }
```

**5d. `handleBackFromInput`** (lines 227-234) — reset the flag next to `setError(null)`:

```ts
  function handleBackFromInput() {
    if (hasChanges) {
      setDiscardOpen(true)
      return
    }
    setStep('source')
    setError(null)
    setLlmFallbackAvailable(false)
  }
```

**5e. Analyze button** (line 417) — `handleAnalyze` now takes a flag, and the raw click event would become a truthy `useServerDefault`. Change `onClick={handleAnalyze}` to:

```tsx
                <button type="button" className="btn btn--primary" onClick={() => void handleAnalyze()} disabled={busy}>
                  {working ? 'Cloning & analyzing…' : 'Analyze repo'}
                </button>
```

**5f. Retry button** — next to the existing error action block (lines 394-398, the "Open manual builder" button), same indentation:

```tsx
                {error && llmFallbackAvailable ? (
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => void handleAnalyze(true)} disabled={busy}>
                    Retry with Vela default
                  </button>
                ) : null}
```

- [ ] **Step 6: `frontend/src/pages/stacks/ServiceEditForm.tsx`**

**6a. Import** — add `isLlmFallbackError` to the existing `'../../api/client'` block (lines 2-9):

```ts
import {
  analyzeGitSource,
  formatApiError,
  isLlmFallbackError,
  uploadVolumeFolder,
  type BuildOverride,
  type ScalingPolicyRequest,
  type StackServiceCreate,
} from '../../api/client'
```

**6b. State** — with the other `useState` declarations (lines 63-72), e.g. after `buildConfigError`:

```ts
  const [llmFallbackAvailable, setLlmFallbackAvailable] = useState(false)
```

**6c. `onAnalyzeGitSource`** (lines 201-221) becomes:

```ts
  async function onAnalyzeGitSource(useServerDefault = false) {
    if (!service.source_ref.trim()) {
      setBuildConfigError('Choose a git repository first.')
      return
    }
    setBuildConfigBusy(true)
    setBuildConfigError(null)
    setLlmFallbackAvailable(false)
    try {
      const analysis = await analyzeGitSource({
        git_url: service.source_ref.trim(),
        git_branch: service.git_branch?.trim() || 'main',
        use_server_default: useServerDefault,
      })
      if (analysis.needs_manual_build_config) {
        openBuildConfigModal(buildOverrideFromAnalysis(analysis))
      }
    } catch (error) {
      setLlmFallbackAvailable(isLlmFallbackError(error))
      setBuildConfigError(formatApiError(error))
    } finally {
      setBuildConfigBusy(false)
    }
  }
```

**6d. Retry button** — after the existing `buildConfigError` paragraph (lines 485-489):

```tsx
          {buildConfigError && llmFallbackAvailable ? (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={buildConfigBusy}
              onClick={() => void onAnalyzeGitSource(true)}
            >
              Retry with Vela default
            </button>
          ) : null}
```

(The existing "Analyze repo" button at lines 451-458 already wraps its handler in an arrow function — leave it.)

- [ ] **Step 7: Verify**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: clean.

- [ ] **Step 8: Commit**

Stage exactly the six files above.

```powershell
git add frontend/src/pages/containers/useGitSourceAnalysis.ts frontend/src/pages/containers/useContainerRunForm.ts frontend/src/pages/containers/ContainersRunFormFields.tsx frontend/src/pages/ContainersPage.tsx frontend/src/pages/stacks/NewStackModal.tsx frontend/src/pages/stacks/ServiceEditForm.tsx
git commit -m "feat: retry source analysis with Vela default when user provider fails"
```

---

## Task 10: E2E coverage + final verification

E2E for the Task 8 settings card: render, save (Anthropic), remove through the confirm dialog, then an API cleanup. Tests run in order within the file (Playwright runs one worker with `fullyParallel: false`), and the cleanup test keeps later specs and re-runs clean. No `page.route` mocking — save/remove make no external provider call, and the cleanup hits the live API with the seeded user's token.

**Files:**
- Create: `frontend/e2e/llm-provider.spec.ts`

- [ ] **Step 1: Create `frontend/e2e/llm-provider.spec.ts`**

The dialog follows `ConfirmDialog.tsx`, which renders `role="dialog"` on the `.stacks-modal` div with the title as its accessible name (`aria-labelledby` on the `h2`) — the same scoping style as `e2e/build-override.spec.ts`:

```ts
import { bearerToken } from './auth-helpers'
import { apiBase } from './constants'
import { test, expect } from './fixtures'

test.describe('LLM provider settings', () => {
  test('renders the LLM provider card with Test disabled while no key is set', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'LLM provider', level: 3 }),
    ).toBeVisible()
    await expect(authenticatedPage.getByLabel('Provider')).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Test' }),
    ).toBeDisabled()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Save' }),
    ).toBeVisible()
  })

  test('saves an Anthropic provider and keeps it after reload', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await authenticatedPage.getByLabel('Provider').selectOption('anthropic')
    await authenticatedPage.getByLabel('API key').fill('sk-ant-e2e-test-key')
    await expect(authenticatedPage.getByLabel('Model')).toHaveValue(
      'claude-sonnet-4-5',
    )
    await authenticatedPage.getByRole('button', { name: 'Save' }).click()
    await expect(authenticatedPage.getByText('LLM provider saved.')).toBeVisible()

    await authenticatedPage.reload()
    await expect(authenticatedPage.getByLabel('Provider')).toHaveValue('anthropic')
    await expect(authenticatedPage.getByLabel('API key')).toHaveAttribute(
      'placeholder',
      'Saved — leave blank to keep',
    )
  })

  test('removes the provider through the confirm dialog', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/settings')
    await authenticatedPage.getByRole('button', { name: 'Remove' }).click()
    const dialog = authenticatedPage.getByRole('dialog', {
      name: 'Remove LLM provider?',
    })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Remove' }).click()
    await expect(
      authenticatedPage.getByText('LLM provider removed.'),
    ).toBeVisible()
  })

  test('cleans up the LLM provider row for later specs', async ({
    authenticatedPage,
  }) => {
    const token = await bearerToken(authenticatedPage)
    const response = await authenticatedPage.request.delete(
      `${apiBase}/api/settings/llm-provider`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    expect(response.status()).toBe(204)
  })
})
```

In the remove test the card's own "Remove" button and the dialog's confirm button share the name; the card button sits outside the dialog (sibling of the modal backdrop), so the dialog-scoped `getByRole('button', { name: 'Remove' })` resolves unambiguously.

- [ ] **Step 2: Final verification**

1. Backend — from `backend/`:
   - `python -m pytest tests -q` — all pass
   - `ruff check .` — clean
   - `mypy app/ tests/` — clean
2. Frontend — from `frontend/`:
   - `npm run lint` — clean
   - `npm run typecheck` — clean
   - `npm run test:e2e` — all pass, including the new spec
3. Compose sanity — from the repo root: `docker compose -f docker-compose.yml config -q` — succeeds.
4. `git status` — clean except intended changes.

- [ ] **Step 3: Commit**

```powershell
git add frontend/e2e/llm-provider.spec.ts
git commit -m "test: e2e coverage for LLM provider settings"
```
