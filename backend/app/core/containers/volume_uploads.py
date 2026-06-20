"""User-scoped folder uploads for read-only container volume mounts."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from app.core.exceptions import (
    InvalidVolumeUploadPathError,
    VolumeUploadNotFoundError,
    VolumeUploadQuotaExceededError,
    VolumeUploadTooLargeError,
)

VOLUME_UPLOAD_MAX_BYTES = 100 * 1024 * 1024
VOLUME_UPLOAD_USER_QUOTA_BYTES = 150 * 1024 * 1024


def volume_upload_max_bytes() -> int:
    raw = os.environ.get("VELA_VOLUME_UPLOAD_MAX_BYTES", "").strip()
    if raw:
        return int(raw)
    return VOLUME_UPLOAD_MAX_BYTES


def volume_upload_user_quota_bytes() -> int:
    raw = os.environ.get("VELA_VOLUME_UPLOAD_USER_QUOTA_BYTES", "").strip()
    if raw:
        return int(raw)
    return VOLUME_UPLOAD_USER_QUOTA_BYTES


def volume_uploads_root() -> Path:
    configured = os.environ.get("VELA_VOLUME_UPLOADS_DIR", "").strip()
    if configured:
        return Path(configured).resolve()
    return (Path.cwd() / "data" / "volume-uploads").resolve()


def user_uploads_root(user_id: uuid.UUID) -> Path:
    return volume_uploads_root() / str(user_id)


def upload_directory(user_id: uuid.UUID, upload_id: uuid.UUID) -> Path:
    return user_uploads_root(user_id) / str(upload_id)


def user_uploads_total_bytes(user_id: uuid.UUID) -> int:
    root = user_uploads_root(user_id)
    if not root.is_dir():
        return 0
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def sanitize_relative_path(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").strip()
    if not normalized:
        msg = "Each uploaded file must have a relative path."
        raise InvalidVolumeUploadPathError(msg)
    if normalized.startswith("/"):
        msg = "Uploaded file paths must be relative to the selected folder."
        raise InvalidVolumeUploadPathError(msg)
    parts = Path(normalized).parts
    if ".." in parts:
        msg = "Uploaded file paths cannot contain '..'."
        raise InvalidVolumeUploadPathError(msg)
    return normalized


def infer_folder_name(relative_paths: list[str]) -> str:
    if not relative_paths:
        return "upload"
    first_path = relative_paths[0].replace("\\", "/")
    top_level = first_path.split("/")[0]
    return top_level or "upload"


def _ensure_upload_within_user_quota(
    user_id: uuid.UUID,
    additional_bytes: int,
) -> None:
    quota_bytes = volume_upload_user_quota_bytes()
    current_usage = user_uploads_total_bytes(user_id)
    if current_usage + additional_bytes > quota_bytes:
        limit_megabytes = quota_bytes // (1024 * 1024)
        msg = (
            f"Upload would exceed your {limit_megabytes} MB volume storage quota. "
            "Use a smaller folder or remove unused uploads."
        )
        raise VolumeUploadQuotaExceededError(msg)


def save_volume_upload(
    user_id: uuid.UUID,
    files: list[tuple[str, bytes]],
) -> tuple[uuid.UUID, str, int, int]:
    """
    Persist uploaded folder files under a new upload id.

    Returns:
        (upload_id, folder_name, total_bytes, file_count)
    """
    if not files:
        msg = "Select a folder that contains at least one file."
        raise InvalidVolumeUploadPathError(msg)

    total_bytes = sum(len(content) for _, content in files)
    per_folder_limit = volume_upload_max_bytes()
    if total_bytes > per_folder_limit:
        limit_megabytes = per_folder_limit // (1024 * 1024)
        msg = f"Folder exceeds the {limit_megabytes} MB upload limit."
        raise VolumeUploadTooLargeError(msg)

    _ensure_upload_within_user_quota(user_id, total_bytes)

    relative_paths = [sanitize_relative_path(path) for path, _ in files]
    upload_id = uuid.uuid4()
    destination_root = upload_directory(user_id, upload_id)
    destination_root.mkdir(parents=True, exist_ok=False)

    try:
        for relative_path, content in zip(relative_paths, (content for _, content in files), strict=True):
            target_path = destination_root / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)
    except Exception:
        shutil.rmtree(destination_root, ignore_errors=True)
        raise

    folder_name = infer_folder_name(relative_paths)
    return upload_id, folder_name, total_bytes, len(files)


def resolve_volume_upload_path(user_id: uuid.UUID, upload_id: uuid.UUID) -> Path:
    root = upload_directory(user_id, upload_id).resolve()
    user_root = user_uploads_root(user_id).resolve()
    if not str(root).startswith(str(user_root)):
        msg = "Volume upload not found."
        raise VolumeUploadNotFoundError(msg)
    if not root.is_dir():
        msg = "Volume upload not found."
        raise VolumeUploadNotFoundError(msg)
    return root
