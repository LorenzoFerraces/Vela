"""Unit tests for Git analysis context collection."""

from __future__ import annotations

from pathlib import Path

from app.core.git.git_source_analysis import (
    _collect_context_excerpts,
    _env_vars_from_payload,
    _extract_env_vars_from_context,
    _merge_env_fallback,
)
from app.api.schemas import GitSourceAnalysis


def test_readme_is_included_before_other_files_when_budget_is_tight(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text(
        "Run on port 8000.\nexport DATABASE_URL=postgres://local\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")

    context = _collect_context_excerpts(tmp_path)

    assert "=== README.md ===" in context
    assert "DATABASE_URL" in context
    assert context.index("README.md") < context.index("Dockerfile")


def test_readme_variant_readme_without_extension(tmp_path: Path) -> None:
    (tmp_path / "README").write_text(
        "VITE_API_BASE_URL=http://localhost:8000\n", encoding="utf-8"
    )

    context = _collect_context_excerpts(tmp_path)

    assert "=== README ===" in context
    assert "VITE_API_BASE_URL" in context


def test_extract_env_vars_from_readme_table() -> None:
    snippet = """
| Variable | Notes |
|----------|--------|
| `VELA_DATABASE_URL` | e.g. `postgresql+asyncpg://vela:vela@127.0.0.1:15432/Vela` |
| `VELA_AUTH_SECRET` | Long random secret |
"""
    env_vars = _extract_env_vars_from_context(snippet)

    assert (
        env_vars["VELA_DATABASE_URL"]
        == "postgresql+asyncpg://vela:vela@127.0.0.1:15432/Vela"
    )
    assert env_vars["VELA_AUTH_SECRET"] == ""


def test_env_vars_from_gemini_entries_payload() -> None:
    env_vars = _env_vars_from_payload(
        {
            "env_var_entries": [
                {"key": "VELA_AUTH_SECRET", "value": "secret"},
                {"key": "VELA_DATABASE_URL", "value": ""},
            ]
        }
    )

    assert env_vars == {
        "VELA_AUTH_SECRET": "secret",
        "VELA_DATABASE_URL": "",
    }


def test_merge_env_fallback_uses_readme_when_model_returns_empty() -> None:
    context = """
=== README.md ===
| `VELA_GEMINI_API_KEY` | Optional |
"""
    analysis = GitSourceAnalysis(
        container_port=8000,
        summary_hint="ok",
    )
    merged = _merge_env_fallback(analysis, context)

    assert "VELA_GEMINI_API_KEY" in merged.env_vars


def test_vela_repo_readme_yields_env_vars() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    context = _collect_context_excerpts(repo_root)
    env_vars = _extract_env_vars_from_context(context)

    assert "VELA_DATABASE_URL" in env_vars
    assert "VELA_AUTH_SECRET" in env_vars
    assert "frontend/.env.example" in context or "VITE_API_BASE_URL" in context
