import pytest

from app.core.exceptions import CloneError
from app.core.git.git_ops import git_shallow_clone
from app.core.security.outbound_url import validate_git_remote


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://169.254.169.254/latest/meta-data/",
    "https://127.0.0.1/x.git",
])
def test_public_git_remote_rejects_private_or_local_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_git_remote(url)


@pytest.mark.asyncio
async def test_clone_rejects_file_scheme(tmp_path) -> None:
    with pytest.raises(CloneError):
        await git_shallow_clone(url="file:///etc/passwd", branch="main", dest=tmp_path / "x")


def test_opt_in_allows_private_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("VELA_GIT_ALLOW_PRIVATE_ENDPOINTS", "1")
    assert validate_git_remote("http://127.0.0.1/x.git") == "http://127.0.0.1/x.git"
