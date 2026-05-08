"""Unit tests for git clone command construction and CloneError sanitization."""

from __future__ import annotations

import asyncio
import base64
import subprocess
from pathlib import Path

import pytest

from app.core import git_ops
from app.core.exceptions import CloneError


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
    assert "***@github.com" in err.git_url
