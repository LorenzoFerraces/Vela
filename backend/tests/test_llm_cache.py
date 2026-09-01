"""Tests for the commit-keyed LLM result cache and git head lookup."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.git.git_ops import head_commit
from app.core.llm import cache as cache_module


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
    monkeypatch.setattr(cache_module.time, "time", lambda: next(stamps))
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
