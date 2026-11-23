"""Unit tests for git clone command construction and CloneError sanitization."""

from __future__ import annotations

import asyncio
import base64
import subprocess
from pathlib import Path

import pytest

from app.core.exceptions import CloneError
from app.core.git import git_ops


def test_clone_command_without_token_keeps_classic_shape(tmp_path: Path) -> None:
    cmd = git_ops._build_clone_command(
        url="https://github.com/org/repo.git",
        branch="main",
        dest=tmp_path / "repo",
        access_token=None,
    )
    assert cmd[0] == "git"
    assert "-c" not in cmd
    assert cmd[1:5] == ["clone", "--depth", "1", "--branch"]


def test_clone_command_with_token_injects_basic_auth_header(tmp_path: Path) -> None:
    token = "ghp_super_secret"
    cmd = git_ops._build_clone_command(
        url="https://github.com/org/repo.git",
        branch="main",
        dest=tmp_path / "repo",
        access_token=token,
    )
    assert cmd[0] == "git"
    assert cmd[1] == "-c"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    assert cmd[2] == f"http.extraheader=Authorization: Basic {encoded}"
    # Token must not appear inside the URL itself.
    assert "ghp_super_secret" not in " ".join(cmd[3:])


def test_clone_command_skips_token_for_non_https_url(tmp_path: Path) -> None:
    cmd = git_ops._build_clone_command(
        url="git@github.com:org/repo.git",
        branch="main",
        dest=tmp_path / "repo",
        access_token="ghp_should_be_ignored",
    )
    assert "-c" not in cmd
    assert "ghp_should_be_ignored" not in " ".join(cmd)


def test_fetch_commands_for_full_sha(tmp_path: Path) -> None:
    sha = "A" * 40
    dest = tmp_path / "repo"
    url = "https://github.com/org/repo.git"
    commands = git_ops._build_fetch_commands(
        url=url, sha=sha, dest=dest, access_token=None
    )
    assert commands == [
        ["git", "init", str(dest)],
        ["git", "-C", str(dest), "remote", "add", "origin", url],
        ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", sha],
        ["git", "-C", str(dest), "checkout", "--detach", "FETCH_HEAD"],
    ]


def test_fetch_commands_carry_auth_header_on_fetch_only(tmp_path: Path) -> None:
    token = "ghp_super_secret"
    commands = git_ops._build_fetch_commands(
        url="https://github.com/org/repo.git",
        sha="a" * 40,
        dest=tmp_path / "repo",
        access_token=token,
    )
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    assert "-c" not in commands[0]
    assert "-c" not in commands[1]
    assert commands[2][1:3] == ["-c", f"http.extraheader=Authorization: Basic {encoded}"]
    assert token not in " ".join(commands[3])
    assert token not in commands[2][-1]


def test_fetch_by_sha_against_real_local_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real git (no E2E stub, no network) checks out a pinned commit by SHA."""
    monkeypatch.delenv("VELA_E2E", raising=False)
    # Local paths are intentionally rejected at the API boundary; the test
    # exercises the git plumbing, not the SSRF guard.
    monkeypatch.setattr(git_ops, "_validate_git_url", lambda url: None)
    monkeypatch.setattr(git_ops, "_guard_git_url", lambda url: url)

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
    (source / "marker.txt").write_text("pinned-commit\n")
    subprocess.run(["git", "-C", str(source), "add", "marker.txt"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "init"], check=True)
    sha = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    dest = tmp_path / "checkout"
    asyncio.run(git_ops.git_shallow_clone(url=str(source), branch=sha, dest=dest))

    assert (dest / "marker.txt").read_text() == "pinned-commit\n"
    head = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == sha


def test_clone_error_url_and_message_mask_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a caller embeds creds in the URL, neither the URL nor stderr should leak them."""

    leaked_url = "https://user:supersecret@github.com/org/repo.git"

    class _FailedCompleted:
        def __init__(self) -> None:
            self.returncode = 128
            self.stderr = (
                "remote: Authentication failed for "
                "'https://user:supersecret@github.com/org/repo.git/'\n"
            )
            self.stdout = ""

    def fake_run(*_args, **_kwargs):
        return _FailedCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(CloneError) as exc_info:
        asyncio.run(
            git_ops.git_shallow_clone(
                url=leaked_url,
                branch="main",
                dest=tmp_path / "repo",
            )
        )

    err = exc_info.value
    assert "supersecret" not in err.git_url
    assert "supersecret" not in str(err)
    assert "github.com" in err.git_url


def test_validate_git_url_requires_scp_colon() -> None:
    git_ops._validate_git_url("git@github.com:org/repo.git")
    with pytest.raises(CloneError):
        git_ops._validate_git_url("git@local-repo")

