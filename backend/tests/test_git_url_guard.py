import socket

import pytest

from app.core.exceptions import CloneError
from app.core.git.git_ops import _guard_git_url, git_head_ref, git_shallow_clone
from app.core.security.outbound_url import validate_git_remote


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://169.254.169.254/latest/meta-data/",
    "https://127.0.0.1/x.git",
])
def test_public_git_remote_rejects_private_or_local_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_git_remote(url)


@pytest.fixture
def internal_host_is_private(monkeypatch: pytest.MonkeyPatch) -> None:
    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host == "internal":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.parametrize("url", [
    "git@127.0.0.1:x.git",
    "git@internal:path",
    "git@[::1]:path",
    "ssh://git@127.0.0.1/x.git",
    "git://127.0.0.1/x.git",
])
def test_scp_ssh_git_private_hosts_rejected(
    url: str, internal_host_is_private: None
) -> None:
    with pytest.raises(CloneError):
        _guard_git_url(url)


@pytest.mark.parametrize("url", [
    "git@github.com:path",
    "ssh://git@github.com/x.git",
    "git://github.com/x.git",
])
def test_scp_ssh_git_public_hosts_allowed(url: str) -> None:
    assert _guard_git_url(url) == url


def test_guard_returns_trimmed_url() -> None:
    assert _guard_git_url("  git@github.com:path  ") == "git@github.com:path"


@pytest.mark.asyncio
async def test_clone_rejects_private_scp_host(tmp_path) -> None:
    with pytest.raises(CloneError):
        await git_shallow_clone(url="git@127.0.0.1:x.git", branch="main", dest=tmp_path / "x")


@pytest.mark.asyncio
async def test_head_ref_rejects_private_scp_host() -> None:
    with pytest.raises(CloneError):
        await git_head_ref(url="git@127.0.0.1:x.git", branch="main")


@pytest.mark.asyncio
async def test_clone_rejects_file_scheme(tmp_path) -> None:
    with pytest.raises(CloneError):
        await git_shallow_clone(url="file:///etc/passwd", branch="main", dest=tmp_path / "x")


def test_opt_in_allows_private_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("VELA_GIT_ALLOW_PRIVATE_ENDPOINTS", "1")
    assert validate_git_remote("http://127.0.0.1/x.git") == "http://127.0.0.1/x.git"
