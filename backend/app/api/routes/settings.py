"""User settings (AI pre-fill preferences)."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    AiPrefillPreferences,
    AiPrefillPreferencesUpdate,
    GeminiConfigStatus,
)
from app.core import user_preferences
from app.db.models import User

router = APIRouter()


@router.get("/ai-prefill", response_model=AiPrefillPreferences)
async def get_ai_prefill_settings(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AiPrefillPreferences:
    return await user_preferences.get_ai_prefill_preferences(session, current_user.id)


@router.patch("/ai-prefill", response_model=AiPrefillPreferences)
async def patch_ai_prefill_settings(
    body: AiPrefillPreferencesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AiPrefillPreferences:
    return await user_preferences.update_ai_prefill_preferences(
        session,
        current_user.id,
        body,
    )


@router.get("/gemini-status", response_model=GeminiConfigStatus)
async def gemini_config_status(
    _current_user: Annotated[User, Depends(get_current_user)],
) -> GeminiConfigStatus:
    configured = bool(os.environ.get("VELA_GEMINI_API_KEY", "").strip())
    return GeminiConfigStatus(configured=configured)
