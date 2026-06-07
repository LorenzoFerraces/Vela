"""Alert service for container monitoring and notification.

Handles alert deduplication, history tracking, and email dispatch.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notifications.email_provider import EmailAlert, EmailProvider
from app.db.models import AlertHistory, EmailPreference, User

logger = logging.getLogger(__name__)

DEDUP_WINDOW_MINUTES = 10
DEFAULT_ALERT_TYPES: list[str] = ["stop", "failure", "unhealthy"]
DEFAULT_ALERT_FREQUENCY = "immediate"


@dataclass(frozen=True)
class EffectiveEmailPreferences:
    email: str
    alerts_enabled: bool
    alert_types: list[str]
    alert_frequency: str


class AlertService:
    def __init__(self, email_provider: EmailProvider, session: AsyncSession):
        self.email_provider = email_provider
        self.session = session

    def _hash_event(self, user_id: uuid.UUID, container_id: str, event_type: str) -> str:
        """Generate hash for deduplication."""
        key = f"{user_id}:{container_id}:{event_type}"
        return hashlib.sha256(key.encode()).hexdigest()

    async def _resolve_effective_preferences(
        self, user_id: uuid.UUID
    ) -> EffectiveEmailPreferences | None:
        """Load saved preferences or the same defaults exposed by GET /email-notifications."""
        stmt = select(EmailPreference).where(EmailPreference.user_id == user_id)
        prefs = await self.session.scalar(stmt)
        if prefs is not None:
            return EffectiveEmailPreferences(
                email=prefs.email,
                alerts_enabled=prefs.alerts_enabled,
                alert_types=list(prefs.alert_types),
                alert_frequency=prefs.alert_frequency,
            )

        user = await self.session.get(User, user_id)
        if user is None or not user.email.strip():
            return None

        return EffectiveEmailPreferences(
            email=user.email,
            alerts_enabled=True,
            alert_types=list(DEFAULT_ALERT_TYPES),
            alert_frequency=DEFAULT_ALERT_FREQUENCY,
        )

    async def _should_send_alert(
        self, user_id: uuid.UUID, container_id: str, event_type: str
    ) -> bool:
        """Check if a successful alert was sent recently (dedup within time window)."""
        alert_hash = self._hash_event(user_id, container_id, event_type)
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=DEDUP_WINDOW_MINUTES)

        stmt = select(AlertHistory).where(
            and_(
                AlertHistory.user_id == user_id,
                AlertHistory.alert_hash == alert_hash,
                AlertHistory.status == "sent",
                AlertHistory.sent_at >= cutoff_time,
            )
        )
        recent_alert = await self.session.scalar(stmt)

        if recent_alert:
            logger.debug(
                "Alert deduped: %s %s (last sent %s min ago)",
                container_id,
                event_type,
                DEDUP_WINDOW_MINUTES,
            )
            return False

        return True

    async def send_container_alert(
        self,
        user_id: uuid.UUID,
        container_id: str,
        container_name: str,
        event_type: str,
        details: str | None = None,
    ) -> bool:
        """Send alert for container event if user has enabled notifications."""
        try:
            effective = await self._resolve_effective_preferences(user_id)
            if effective is None or not effective.alerts_enabled:
                logger.debug("Alerts disabled for user %s", user_id)
                return False

            if event_type not in effective.alert_types:
                logger.debug("Event type %s not in user alert types", event_type)
                return False

            if effective.alert_frequency != DEFAULT_ALERT_FREQUENCY:
                logger.debug(
                    "Skipping alert for user %s: frequency %r is not supported yet",
                    user_id,
                    effective.alert_frequency,
                )
                return False

            if not await self._should_send_alert(user_id, container_id, event_type):
                return False

            alert = EmailAlert(
                to=effective.email,
                container_name=container_name,
                event_type=event_type,
                timestamp=datetime.now(timezone.utc),
                details=details,
            )

            success = await self.email_provider.send_alert(alert)
            if not success:
                return False

            alert_hash = self._hash_event(user_id, container_id, event_type)
            history_record = AlertHistory(
                user_id=user_id,
                container_id=container_id,
                event_type=event_type,
                alert_hash=alert_hash,
                sent_at=datetime.now(timezone.utc),
                email_sent_to=effective.email,
                status="sent",
            )
            self.session.add(history_record)
            await self.session.commit()

            return True

        except Exception:
            logger.exception("Error sending alert for user %s", user_id)
            return False

    async def get_recent_alerts(
        self, user_id: uuid.UUID, container_id: str | None = None, limit: int = 10
    ) -> list[AlertHistory]:
        """Get recent alerts for a user, optionally filtered by container."""
        stmt = select(AlertHistory).where(AlertHistory.user_id == user_id)

        if container_id:
            stmt = stmt.where(AlertHistory.container_id == container_id)

        stmt = stmt.order_by(desc(AlertHistory.sent_at)).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
