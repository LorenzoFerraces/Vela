"""Map domain profile snapshots to API response models."""

from __future__ import annotations

from app.api.schemas import UserPublic
from app.core.profile.models import UserProfileSnapshot


def user_public_from_snapshot(snapshot: UserProfileSnapshot) -> UserPublic:
    return UserPublic(
        id=snapshot.id,
        email=snapshot.email,
        created_at=snapshot.created_at,
        display_name=snapshot.display_name,
        pronouns=snapshot.pronouns,
        avatar_url=snapshot.avatar_url,
    )
