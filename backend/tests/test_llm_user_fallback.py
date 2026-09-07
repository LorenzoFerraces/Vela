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
