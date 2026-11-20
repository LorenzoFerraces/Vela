"""Tests for streaming upload limits, quota locking, and path containment."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.containers import volume_uploads
from app.core.exceptions import InvalidVolumeUploadPathError


class _FakeUpload:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


@pytest.mark.asyncio
async def test_read_upload_limited_enforces_limit_while_streaming() -> None:
    upload = _FakeUpload([b"a" * 64, b"b" * 64])
    with pytest.raises(Exception) as exc:
        await volume_uploads.read_upload_limited(upload, 100)  # type: ignore[arg-type]
    assert type(exc.value).__name__ == "VolumeUploadTooLargeError"


def test_clamped_declared_size_is_ignored() -> None:
    """A client may claim size=1 while sending more bytes; the stream enforces the limit."""
    upload = _FakeUpload([b"x" * 200])
    with pytest.raises(Exception) as exc:
        asyncio.run(volume_uploads.read_upload_limited(upload, 100))  # type: ignore[arg-type]
    assert type(exc.value).__name__ == "VolumeUploadTooLargeError"


def test_resolve_upload_path_rejects_sibling_prefix(monkeypatch, tmp_path) -> None:
    """A resolved dir sharing only the user-id string prefix is rejected."""
    user_id = uuid.uuid4()
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path))
    sibling = tmp_path / f"{user_id}-evil"
    sibling.mkdir()
    # Simulate a crafted directory whose name starts with the user id but is not
    # beneath it -- the string-prefix containment escape this test guards against.
    monkeypatch.setattr(volume_uploads, "upload_directory", lambda uid, upl: sibling)
    with pytest.raises(InvalidVolumeUploadPathError):
        volume_uploads.resolve_volume_upload_path(user_id, uuid.uuid4())
