"""User profile updates and avatar uploads."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.profile.models import UserProfileSnapshot
from app.core.exceptions import AvatarValidationError
from app.core.storage.object_storage import ObjectStorage
from app.db.models import User

MAX_AVATAR_BYTES = 2 * 1024 * 1024
ALLOWED_AVATAR_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)

_CONTENT_TYPE_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def avatar_cache_bust(user: User) -> str | None:
    if user.avatar_updated_at is None:
        return None
    return str(int(user.avatar_updated_at.timestamp()))


def avatar_public_url(user: User, object_storage: ObjectStorage) -> str | None:
    if not user.avatar_object_key:
        return None
    return object_storage.public_url(
        key=user.avatar_object_key,
        cache_bust=avatar_cache_bust(user),
    )


def user_to_snapshot(user: User, object_storage: ObjectStorage) -> UserProfileSnapshot:
    return UserProfileSnapshot(
        id=user.id,
        email=user.email,
        created_at=user.created_at,
        display_name=user.display_name,
        pronouns=user.pronouns,
        avatar_url=avatar_public_url(user, object_storage),
    )


async def update_profile(
    session: AsyncSession,
    user: User,
    *,
    display_name: str | None | object = ...,
    pronouns: str | None | object = ...,
    object_storage: ObjectStorage,
) -> UserProfileSnapshot:
    if display_name is not ...:
        user.display_name = display_name  # type: ignore[assignment]
    if pronouns is not ...:
        user.pronouns = pronouns  # type: ignore[assignment]
    await session.commit()
    await session.refresh(user)
    return user_to_snapshot(user, object_storage)


def detect_image_content_type(body: bytes) -> str | None:
    if len(body) >= 3 and body[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(body) >= 8 and body[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_avatar_bytes(body: bytes) -> str:
    if len(body) == 0:
        raise AvatarValidationError("Avatar file is empty.")
    if len(body) > MAX_AVATAR_BYTES:
        raise AvatarValidationError("Avatar must be 2 MB or smaller.")
    content_type = detect_image_content_type(body)
    if content_type is None or content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
        raise AvatarValidationError(
            "Avatar must be a JPEG, PNG, or WebP image."
        )
    return content_type


def build_avatar_object_key(user_id: uuid.UUID, content_type: str) -> str:
    extension = _CONTENT_TYPE_TO_EXT[content_type]
    return f"avatars/{user_id}/{uuid.uuid4()}.{extension}"


async def upload_avatar(
    session: AsyncSession,
    user: User,
    *,
    body: bytes,
    object_storage: ObjectStorage,
) -> UserProfileSnapshot:
    content_type = validate_avatar_bytes(body)
    new_key = build_avatar_object_key(user.id, content_type)
    previous_key = user.avatar_object_key

    await object_storage.put_object(
        key=new_key,
        body=body,
        content_type=content_type,
    )

    user.avatar_object_key = new_key
    user.avatar_updated_at = datetime.now(timezone.utc)

    try:
        await session.commit()
        await session.refresh(user)
    except Exception:
        await session.rollback()
        try:
            await object_storage.delete_object(key=new_key)
        except Exception as cleanup_error:
            logger.warning(
                "Failed to clean up orphaned avatar object %r after DB rollback: %s",
                new_key,
                cleanup_error,
            )
        raise

    if previous_key and previous_key != new_key:
        try:
            await object_storage.delete_object(key=previous_key)
        except Exception as delete_error:
            logger.warning(
                "Failed to delete previous avatar object %r: %s",
                previous_key,
                delete_error,
            )

    return user_to_snapshot(user, object_storage)


async def delete_avatar(
    session: AsyncSession,
    user: User,
    *,
    object_storage: ObjectStorage,
) -> UserProfileSnapshot:
    previous_key = user.avatar_object_key
    user.avatar_object_key = None
    user.avatar_updated_at = None
    await session.commit()
    await session.refresh(user)

    if previous_key:
        try:
            await object_storage.delete_object(key=previous_key)
        except Exception as delete_error:
            logger.warning(
                "Failed to delete avatar object %r during removal: %s",
                previous_key,
                delete_error,
            )

    return user_to_snapshot(user, object_storage)
