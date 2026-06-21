"""User settings (AI pre-fill preferences and email notifications)."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    AiPrefillPreferences,
    AiPrefillPreferencesUpdate,
    AlertHistoryEntry,
    ContainerMonitoringStatus,
    EmailNotificationPreferences,
    EmailNotificationPreferencesUpdate,
    GeminiConfigStatus,
)
from app.core import user_preferences
from app.core.notifications.alert_service import DEFAULT_ALERT_FREQUENCY, DEFAULT_ALERT_TYPES
from app.core.notifications.container_monitor import (
    MONITOR_ENABLED,
    MONITOR_INTERVAL_SECONDS,
    get_tracked_container_count,
)
from app.db.models import AlertHistory, EmailPreference, User

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


@router.get("/email-notifications", response_model=EmailNotificationPreferences)
async def get_email_notification_settings(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EmailNotificationPreferences:
    """Get user's email notification preferences."""
    stmt = select(EmailPreference).where(EmailPreference.user_id == current_user.id)
    prefs = await session.scalar(stmt)

    if not prefs:
        # Return defaults if not yet created
        return EmailNotificationPreferences(
            id=None,
            user_id=current_user.id,
            email=current_user.email,
            alerts_enabled=True,
            alert_types=list(DEFAULT_ALERT_TYPES),
            alert_frequency=DEFAULT_ALERT_FREQUENCY,
            created_at=current_user.created_at,
            updated_at=current_user.created_at,
        )

    return EmailNotificationPreferences.model_validate(prefs)


@router.patch("/email-notifications", response_model=EmailNotificationPreferences)
async def update_email_notification_settings(
    body: EmailNotificationPreferencesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EmailNotificationPreferences:
    """Update user's email notification preferences."""
    stmt = select(EmailPreference).where(EmailPreference.user_id == current_user.id)
    prefs = await session.scalar(stmt)

    if not prefs:
        # Create new preference record
        prefs = EmailPreference(
            user_id=current_user.id,
            email=body.email or current_user.email,
            alerts_enabled=body.alerts_enabled if body.alerts_enabled is not None else True,
            alert_types=body.alert_types or list(DEFAULT_ALERT_TYPES),
            alert_frequency=body.alert_frequency or DEFAULT_ALERT_FREQUENCY,
        )
        session.add(prefs)
    else:
        # Update existing
        if body.email is not None:
            prefs.email = body.email
        if body.alerts_enabled is not None:
            prefs.alerts_enabled = body.alerts_enabled
        if body.alert_types is not None:
            prefs.alert_types = body.alert_types
        if body.alert_frequency is not None:
            prefs.alert_frequency = body.alert_frequency

    await session.commit()
    await session.refresh(prefs)
    return EmailNotificationPreferences.model_validate(prefs)


@router.get("/email-notifications/history", response_model=list[AlertHistoryEntry])
async def get_alert_history(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
    container_id: str | None = None,
) -> list[AlertHistoryEntry]:
    """Get recent alerts sent to user."""
    stmt = select(AlertHistory).where(AlertHistory.user_id == current_user.id)

    if container_id:
        stmt = stmt.where(AlertHistory.container_id == container_id)

    stmt = stmt.order_by(AlertHistory.sent_at.desc()).limit(limit)
    result = await session.execute(stmt)
    entries = result.scalars().all()
    return [AlertHistoryEntry.model_validate(e) for e in entries]


@router.get("/monitoring/status", response_model=ContainerMonitoringStatus)
async def get_container_monitoring_status(
    _current_user: Annotated[User, Depends(get_current_user)],
) -> ContainerMonitoringStatus:
    """Get container monitoring system status."""
    return ContainerMonitoringStatus(
        enabled=MONITOR_ENABLED,
        interval_seconds=MONITOR_INTERVAL_SECONDS,
        total_containers_tracked=get_tracked_container_count(),
    )

