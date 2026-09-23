"""User settings (AI pre-fill, LLM provider, and email notifications)."""

from __future__ import annotations

from typing import Annotated, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
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
    LlmProviderGet,
    LlmProviderKind,
    LlmProviderSet,
    LlmProviderTestRequest,
    LlmProviderTestResponse,
)
from app.core import user_preferences
from app.core.exceptions import LlmCallError
from app.core.llm import resolve_llm_config
from app.core.llm.registry import get_provider
from app.core.llm.user_config import (
    config_from_parts,
    delete_user_llm_provider,
    get_user_llm_provider,
    set_user_llm_provider,
)
from app.core.notifications.alert_service import DEFAULT_ALERT_FREQUENCY, DEFAULT_ALERT_TYPES
from app.core.notifications.container_monitor import (
    MONITOR_ENABLED,
    get_monitor_interval_seconds,
    get_tracked_container_count,
)
from app.db.models import AlertHistory, EmailPreference, User, UserLlmProvider

router = APIRouter()


def _provider_to_get(row: UserLlmProvider) -> LlmProviderGet:
    return LlmProviderGet(
        provider=cast(LlmProviderKind, row.provider),
        base_url=row.base_url,
        model=row.model,
        has_key=row.api_key_encrypted is not None,
    )


def _llm_test_failure_message(exc: LlmCallError) -> str:
    cause = exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        if cause.response.status_code in (401, 403):
            return "Invalid API key."
        return "The provider rejected the request."
    if isinstance(
        cause,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.PoolTimeout,
        ),
    ):
        return "Endpoint unreachable. Check the base URL and API key."
    return "Could not reach the provider. Try again."


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
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> GeminiConfigStatus:
    row = await get_user_llm_provider(session, current_user.id)
    return GeminiConfigStatus(
        configured=resolve_llm_config() is not None or row is not None,
        user_provider=_provider_to_get(row) if row is not None else None,
    )


@router.get("/llm-provider", response_model=LlmProviderGet | None)
async def get_llm_provider(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> LlmProviderGet | None:
    row = await get_user_llm_provider(session, current_user.id)
    return _provider_to_get(row) if row is not None else None


@router.put("/llm-provider", response_model=LlmProviderGet)
async def put_llm_provider(
    body: LlmProviderSet,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> LlmProviderGet:
    row = await set_user_llm_provider(
        session,
        current_user.id,
        provider=body.provider,
        base_url=body.base_url,
        model=body.model,
        api_key=body.api_key,
    )
    return _provider_to_get(row)


@router.delete("/llm-provider", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_provider(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await delete_user_llm_provider(session, current_user.id)


@router.post("/llm-provider/test", response_model=LlmProviderTestResponse)
async def test_llm_provider_route(
    body: LlmProviderTestRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> LlmProviderTestResponse:
    config = config_from_parts(
        provider=body.provider,
        base_url=body.base_url,
        model=body.model,
        api_key=body.api_key,
    )
    try:
        models = await get_provider(config).verify(config)
    except LlmCallError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_llm_test_failure_message(exc),
        ) from exc
    return LlmProviderTestResponse(ok=True, models=models)


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
        interval_seconds=get_monitor_interval_seconds(),
        total_containers_tracked=get_tracked_container_count(),
    )

