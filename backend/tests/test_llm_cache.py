"""Tests for the commit-keyed LLM result cache and git head lookup."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from app.core.exceptions import GitSourceAnalysisError, LlmCallError
from app.core.git import git_source_analysis
from app.core.git.git_ops import head_commit
from app.core.llm import cache as cache_module
from app.core.stacks import repo_analysis

VALID_GIT_SOURCE_PAYLOAD = {
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
def isolated_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("VELA_LLM_CACHE", raising=False)


def test_store_then_load_returns_same_payload() -> None:
    payload = {"services": [], "summary_hint": "ok"}
    cache_module.store_cached("stacks", "abc123", "v2", payload)
    assert cache_module.load_cached("stacks", "abc123", "v2") == payload


def test_wrong_commit_or_version_returns_none() -> None:
    cache_module.store_cached("stacks", "abc123", "v2", {"a": 1})
    assert cache_module.load_cached("stacks", "def456", "v2") is None
    assert cache_module.load_cached("stacks", "abc123", "v1") is None


def test_disabled_cache_noops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_LLM_CACHE", "0")
    cache_module.store_cached("stacks", "abc123", "v2", {"a": 1})
    assert list(tmp_path.glob("llm_analysis_*.json")) == []
    assert cache_module.load_cached("stacks", "abc123", "v2") is None


def test_eviction_keeps_newest_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache_module, "_MAX_ENTRIES", 3)
    stamps = iter([1, 2, 3, 4, 5])
    monkeypatch.setattr(
        cache_module, "time", types.SimpleNamespace(time=lambda: next(stamps))
    )
    for index in range(5):
        cache_module.store_cached("stacks", f"commit{index}", "v2", {"index": index})
    for index in range(2):
        assert cache_module.load_cached("stacks", f"commit{index}", "v2") is None
    for index in range(2, 5):
        assert (
            cache_module.load_cached("stacks", f"commit{index}", "v2")
            == {"index": index}
        )


def test_empty_commit_is_not_cached() -> None:
    cache_module.store_cached("stacks", "", "v2", {"a": 1})
    assert cache_module.load_cached("stacks", "", "v2") is None


def test_delete_removes_entry() -> None:
    cache_module.store_cached("stacks", "abc123", "v2", {"a": 1})
    cache_module.delete_cached("stacks", "abc123", "v2")
    assert cache_module.load_cached("stacks", "abc123", "v2") is None


def test_delete_missing_key_or_file_is_noop(tmp_path: Path) -> None:
    cache_module.store_cached("stacks", "abc123", "v2", {"a": 1})
    cache_module.delete_cached("stacks", "def456", "v2")
    cache_module.delete_cached("git_source", "abc123", "v1")
    assert cache_module.load_cached("stacks", "abc123", "v2") == {"a": 1}
    assert not (tmp_path / "llm_analysis_git_source.json").exists()


def test_delete_disabled_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_LLM_CACHE", "0")
    path = tmp_path / "llm_analysis_stacks.json"
    path.write_text('{"v2:abc123": {"ts": 1, "payload": {"a": 1}}}', encoding="utf-8")
    cache_module.delete_cached("stacks", "abc123", "v2")
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "v2:abc123": {"ts": 1, "payload": {"a": 1}}
    }


def test_git_source_cache_key_includes_requested_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_generate_json(*, prompt: str, schema: dict) -> dict:
        nonlocal calls
        calls += 1
        return dict(VALID_GIT_SOURCE_PAYLOAD)

    monkeypatch.setattr(git_source_analysis, "generate_json", fake_generate_json)
    url = "https://github.com/org/repo.git"
    asyncio.run(git_source_analysis._call_gemini("", url, "main", "", "abc123"))
    asyncio.run(git_source_analysis._call_gemini("", url, "release-1.0", "", "abc123"))
    asyncio.run(git_source_analysis._call_gemini("", url, "main", "", "abc123"))
    assert calls == 2


def test_git_source_invalid_payload_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def bad_generate_json(*, prompt: str, schema: dict) -> dict:
        return {"container_port": "not-a-port"}

    monkeypatch.setattr(git_source_analysis, "generate_json", bad_generate_json)
    with pytest.raises(GitSourceAnalysisError):
        asyncio.run(
            git_source_analysis._call_gemini(
                "", "https://github.com/org/repo.git", "main", "", "abc123"
            )
        )
    assert (
        cache_module.load_cached(
            "git_source", "abc123:main", git_source_analysis.GIT_SOURCE_PROMPT_VERSION
        )
        is None
    )


def test_stacks_invalid_payload_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad_generate_json(*, prompt: str, schema: dict) -> dict:
        return {"services": []}

    monkeypatch.setattr(repo_analysis, "generate_json", bad_generate_json)
    with pytest.raises(LlmCallError):
        asyncio.run(
            repo_analysis._generate_services(
                context="",
                manifest=None,
                git_url="https://github.com/org/repo.git",
                git_branch="main",
                warnings=[],
                root=tmp_path,
                commit="abc123",
            )
        )
    assert (
        cache_module.load_cached(
            "stacks", "abc123", repo_analysis.STACKS_PROMPT_VERSION
        )
        is None
    )


class _StubImageBuilder:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def clone_repository(
        self,
        git_url: str,
        *,
        branch: str = "main",
        access_token: str | None = None,
    ) -> str:
        _ = git_url, branch, access_token
        return str(self._root)


def _disable_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELA_E2E", raising=False)
    monkeypatch.delenv("VELA_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VELA_VERTEX_API_KEY", raising=False)
    monkeypatch.delenv("VELA_VERTEX_PROJECT_ID", raising=False)


def test_git_source_fallback_path_skips_commit_and_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM-only work ran on the fallback path")

    monkeypatch.setattr(git_source_analysis, "head_commit", boom)
    monkeypatch.setattr(git_source_analysis, "_detected_facts_block", boom)
    _disable_llm_env(monkeypatch)
    root = tmp_path / "repo"
    root.mkdir()
    analysis = asyncio.run(
        git_source_analysis.analyze_git_source(
            _StubImageBuilder(root),
            git_url="https://github.com/org/repo.git",
            git_branch="main",
            access_token=None,
        )
    )
    assert analysis.git_branch == "main"


def test_head_commit_without_git_repo_returns_none(tmp_path: Path) -> None:
    assert head_commit(tmp_path) is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_head_commit_returns_head_sha(tmp_path: Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(args, check=True, capture_output=True)

    run("git", "init", str(tmp_path))
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    run("git", "-C", str(tmp_path), "add", "file.txt")
    run(
        "git",
        "-C",
        str(tmp_path),
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=Test",
        "commit",
        "-m",
        "init",
    )
    expected = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_commit(tmp_path) == expected
