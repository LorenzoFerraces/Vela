"""Per-user UI preferences stored on the User row."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AiPrefillPreferences, AiPrefillPreferencesUpdate
from app.db.models import User

_DEFAULT_AI_PREFILL = AiPrefillPreferences()


def default_ai_prefill_preferences() -> AiPrefillPreferences:
    return AiPrefillPreferences()


def merge_ai_prefill_preferences(
    stored: dict | None,
) -> AiPrefillPreferences:
    if not stored:
        return default_ai_prefill_preferences()
    return AiPrefillPreferences.model_validate(
        {**_DEFAULT_AI_PREFILL.model_dump(), **stored}
    )


async def get_ai_prefill_preferences(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> AiPrefillPreferences:
    user = await session.get(User, user_id)
    if user is None:
        return default_ai_prefill_preferences()
    return merge_ai_prefill_preferences(user.ai_prefill_preferences)


async def update_ai_prefill_preferences(
    session: AsyncSession,
    user_id: uuid.UUID,
    patch: AiPrefillPreferencesUpdate,
) -> AiPrefillPreferences:
    user = await session.get(User, user_id)
    if user is None:
        raise ValueError("User not found.")
    current = merge_ai_prefill_preferences(user.ai_prefill_preferences)
    updated = current.model_copy(
        update=patch.model_dump(exclude_unset=True),
    )
    user.ai_prefill_preferences = updated.model_dump()
    await session.commit()
    await session.refresh(user)
    return updated
