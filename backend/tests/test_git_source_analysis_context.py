"""Unit tests for Git analysis context collection."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.git.git_source_analysis import (
    _collect_context_excerpts,
    _detected_facts_block,
    _dockerfile_facts,
    _env_vars_from_payload,
    _extract_env_vars_from_context,
    _extract_readme_sections,
    _merge_env_fallback,
    _repo_map,
    _select_readme_text,
    _subdir_marker_files,
)
from app.api.schemas import GitSourceAnalysis


def test_context_order_prefers_env_examples_and_dockerfile(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "Run on port 8000.\nexport DATABASE_URL=postgres://local\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text("PORT=8000\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")

    context = _collect_context_excerpts(tmp_path)

    assert "=== README.md ===" in context
    assert "DATABASE_URL" in context
    assert context.index(".env.example") < context.index("Dockerfile")
    assert context.index("Dockerfile") < context.index("README.md")


def test_readme_variant_readme_without_extension(tmp_path: Path) -> None:
    (tmp_path / "README").write_text(
        "VITE_API_BASE_URL=http://localhost:8000\n", encoding="utf-8"
    )

    context = _collect_context_excerpts(tmp_path)

    assert "=== README ===" in context
    assert "VITE_API_BASE_URL" in context


def test_extract_readme_sections_reaches_env_table_past_head_truncation() -> None:
    filler = "\n".join(
        f"## Changelog {index}\n\n"
        f"Release notes item {index} with enough filler text to pad the file.\n"
        for index in range(200)
    )
    readme = (
        "# Big App\n\nIntro line.\n\n"
        f"{filler}\n\n"
        "## Installation and Setup\n\n"
        "This section is long enough to survive the section floor. " * 20 + "\n\n"
        "## Environment\n\n"
        "| Variable | Notes |\n|---|---|\n"
        "| `LATE_KEY` | `late-value` |\n| `LATE_OTHER` | `other` |\n"
    )
    assert len(readme.encode("utf-8")) > 12_000
    assert readme.index("LATE_KEY") > 12_000

    selected = _extract_readme_sections(readme)

    assert "LATE_KEY" in selected
    assert "late-value" in selected
    assert "## Installation and Setup" in selected
    assert "## Changelog 50" not in selected


def test_select_readme_text_keeps_env_table_in_short_kept_section() -> None:
    filler = "".join(f"## Changelog {index}\n\nPatched item {index}.\n" for index in range(400))
    readme = filler + (
        "## Environment\n\n"
        "| Variable | Notes |\n|---|---|\n| `LATE_KEY` | `late-value` |\n"
    )
    assert len(readme.encode("utf-8")) > 12_000
    assert readme.index("LATE_KEY") > 12_000

    selected = _select_readme_text(readme)

    assert "LATE_KEY" in selected
    assert "late-value" in selected
    assert "## Changelog 50" not in selected


def test_extract_readme_sections_flat_file_keeps_env_lines_only() -> None:
    readme = "no headings here, just prose to pad the file.\n" * 700 + "PORT=3000\n"
    assert len(readme.encode("utf-8")) > 12_000

    selected = _extract_readme_sections(readme)
    lines = selected.splitlines()

    assert "PORT=3000" in lines
    assert len(lines) <= 3


def test_select_readme_text_returns_small_readme_unchanged() -> None:
    readme = "# Tiny\n\n## Environment\n\nPORT=3000\n"

    assert _select_readme_text(readme) == readme


def test_repo_map_lists_files_and_skips_ignored(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("x", encoding="utf-8")
    (tmp_path / ".hidden").write_text("x", encoding="utf-8")

    lines = _repo_map(tmp_path).splitlines()

    assert lines == ["app.py", "src/main.py"]


def test_repo_map_skips_symlink_cycles(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x", encoding="utf-8")
    link = tmp_path / "loop"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, ValueError):
        pytest.skip("symlinks not supported in this environment")
    try:
        lines = _repo_map(tmp_path).splitlines()
    finally:
        link.unlink()
    assert lines == ["app.py"]


def test_empty_repo_falls_back_to_analysis_block(tmp_path: Path) -> None:
    context = _collect_context_excerpts(tmp_path)

    assert "=== analysis ===" in context
    assert "language=" in context


def test_repo_map_respects_entry_cap(tmp_path: Path) -> None:
    for index in range(200):
        (tmp_path / f"file_{index:03d}.txt").write_text("x", encoding="utf-8")

    lines = _repo_map(tmp_path).splitlines()

    assert len(lines) == 151
    assert lines[-1] == "…"
    assert lines[:150] == sorted(lines[:150])


def test_subdir_marker_files_on_sparse_root(tmp_path: Path) -> None:
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / ".env.example").write_text("PORT=3000\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "Dockerfile").write_text("FROM node\n", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "readme.txt").write_text("x", encoding="utf-8")

    files = _subdir_marker_files(tmp_path)

    assert [label for label, _ in files] == ["api/Dockerfile", "web/.env.example"]
    assert "FROM python:3.12" in files[0][1]
    assert "PORT=3000" in files[1][1]


def test_subdir_marker_files_empty_when_root_has_markers(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "Dockerfile").write_text("FROM node\n", encoding="utf-8")

    assert _subdir_marker_files(tmp_path) == []


def test_dockerfile_facts_multi_stage_last_from_wins() -> None:
    text = (
        "# comment line\n"
        "FROM golang:1.22 AS build\n"
        "RUN go build -o app .\n"
        "\n"
        "FROM --platform=$TARGETPLATFORM alpine:3.20 AS final\n"
        "EXPOSE 8080\n"
        "EXPOSE 8080/tcp\n"
        "EXPOSE 9090\n"
        'CMD ["./app", "--port", "8080"]\n'
    )

    assert _dockerfile_facts(text) == (
        'base=alpine:3.20 expose=8080,9090 cmd=CMD ["./app", "--port", "8080"]'
    )


def test_dockerfile_facts_none_when_no_instructions() -> None:
    assert _dockerfile_facts("# only a comment\n") is None


def test_detected_facts_block_lists_language_and_documented_env(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "## Environment\n\n| Variable | Notes |\n|---|---|\n"
        "| `WEB_PORT` | `8080` |\n| `LOG_LEVEL` | `info` |\n",
        encoding="utf-8",
    )
    context = _collect_context_excerpts(tmp_path)

    block = _detected_facts_block(tmp_path, context)
    lines = block.splitlines()

    assert lines[0] == "- language=python"
    assert "- documented env vars: WEB_PORT=8080, LOG_LEVEL" in lines


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
