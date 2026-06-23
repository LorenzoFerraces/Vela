"""Unit tests for user volume folder uploads."""

from __future__ import annotations

import uuid

import pytest

from app.core.containers.volume_uploads import (
    VOLUME_UPLOAD_MAX_BYTES,
    VOLUME_UPLOAD_USER_QUOTA_BYTES,
    infer_folder_name,
    resolve_volume_upload_path,
    sanitize_relative_path,
    save_volume_upload,
    upload_directory,
    user_uploads_total_bytes,
)
from app.core.exceptions import (
    InvalidVolumeUploadPathError,
    VolumeUploadNotFoundError,
    VolumeUploadQuotaExceededError,
    VolumeUploadTooLargeError,
)


def test_sanitize_relative_path_rejects_parent_segments() -> None:
    with pytest.raises(InvalidVolumeUploadPathError):
        sanitize_relative_path("../etc/passwd")


def test_infer_folder_name_from_paths() -> None:
    assert infer_folder_name(["assets/config.json"]) == "assets"


def test_save_and_resolve_volume_upload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path))
    user_id = uuid.uuid4()
    upload_id, folder_name, total_bytes, file_count = save_volume_upload(
        user_id,
        [("project/data.txt", b"hello")],
    )
    assert folder_name == "project"
    assert total_bytes == 5
    assert file_count == 1
    resolved = resolve_volume_upload_path(user_id, upload_id)
    assert resolved == upload_directory(user_id, upload_id)
    assert (resolved / "project" / "data.txt").read_text() == "hello"


def test_save_volume_upload_rejects_oversized_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path))
    user_id = uuid.uuid4()
    oversized = b"x" * (VOLUME_UPLOAD_MAX_BYTES + 1)
    with pytest.raises(VolumeUploadTooLargeError):
        save_volume_upload(user_id, [("big.bin", oversized)])


def test_save_volume_upload_rejects_when_user_quota_exceeded(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path))
    user_id = uuid.uuid4()
    first_size = VOLUME_UPLOAD_USER_QUOTA_BYTES - (50 * 1024 * 1024)
    save_volume_upload(user_id, [("first.bin", b"x" * first_size)])

    assert user_uploads_total_bytes(user_id) == first_size

    with pytest.raises(VolumeUploadQuotaExceededError):
        save_volume_upload(user_id, [("second.bin", b"x" * (60 * 1024 * 1024))])


def test_resolve_missing_upload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VELA_VOLUME_UPLOADS_DIR", str(tmp_path))
    with pytest.raises(VolumeUploadNotFoundError):
        resolve_volume_upload_path(uuid.uuid4(), uuid.uuid4())
