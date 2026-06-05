"""Email provider abstraction for sending alerts.

Uses the official Brevo Python SDK (``brevo-python``) for transactional email.
See https://developers.brevo.com/guides/python
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from brevo import AsyncBrevo
from brevo.core.api_error import ApiError
from brevo.transactional_emails.types.send_transac_email_request_sender import (
    SendTransacEmailRequestSender,
)
from brevo.transactional_emails.types.send_transac_email_request_to_item import (
    SendTransacEmailRequestToItem,
)

logger = logging.getLogger(__name__)

BREVO_ALERT_TAG = "vela-container-alert"


@dataclass
class EmailAlert:
    to: str
    container_name: str
    event_type: str
    timestamp: datetime
    details: str | None = None


class EmailProvider(ABC):
    @abstractmethod
    async def send_alert(self, alert: EmailAlert) -> bool:
        """Send an alert email. Return True if successful."""
        pass


def format_alert_email(alert: EmailAlert) -> tuple[str, str]:
    """Return (subject, plain-text body) for a container alert."""
    subject = f"[Vela Alert] {alert.container_name} - {alert.event_type.upper()}"
    details_line = f"Details: {alert.details}\n\n" if alert.details else ""
    body = (
        "Container Alert Notification\n\n"
        f"Container: {alert.container_name}\n"
        f"Event: {alert.event_type}\n"
        f"Time: {alert.timestamp.isoformat()}\n\n"
        f"{details_line}"
        "This is an automated alert from Vela container platform.\n"
        "Please check your container status immediately."
    )
    return subject, body


class BrevoProvider(EmailProvider):
    """Brevo transactional email provider via ``AsyncBrevo``."""

    def __init__(
        self,
        api_key: str,
        sender_email: str,
        sender_name: str = "Vela",
        *,
        client: AsyncBrevo | None = None,
    ) -> None:
        self.api_key = api_key
        self.sender_email = sender_email
        self.sender_name = sender_name
        self._client = client or AsyncBrevo(api_key=api_key, timeout=10.0)

    async def send_alert(self, alert: EmailAlert) -> bool:
        """Send alert via Brevo transactional email API."""
        if not self.api_key or not self.sender_email:
            logger.warning("Brevo not configured. Skipping email send.")
            return False

        subject, body = format_alert_email(alert)
        try:
            result = await self._client.transactional_emails.send_transac_email(
                subject=subject,
                text_content=body,
                sender=SendTransacEmailRequestSender(
                    email=self.sender_email,
                    name=self.sender_name,
                ),
                to=[SendTransacEmailRequestToItem(email=alert.to)],
                tags=[BREVO_ALERT_TAG],
                request_options={"timeout_in_seconds": 10},
            )
        except ApiError as error:
            logger.error("Brevo API error: %s %s", error.status_code, error.body)
            return False
        except Exception as error:
            logger.error("Failed to send email via Brevo: %s", error)
            return False

        message_id = getattr(result, "message_id", None)
        logger.info(
            "Email sent to %s for %s (message_id=%s)",
            alert.to,
            alert.container_name,
            message_id,
        )
        return True


class ConsoleProvider(EmailProvider):
    """Development provider that logs alerts to console instead of sending emails."""

    async def send_alert(self, alert: EmailAlert) -> bool:
        logger.info(
            f"[ALERT] To: {alert.to} | Container: {alert.container_name} | "
            f"Event: {alert.event_type} | Time: {alert.timestamp.isoformat()}"
        )
        return True


def get_email_provider(use_console: bool = False) -> EmailProvider:
    """Factory to get configured email provider."""
    import os

    if use_console:
        return ConsoleProvider()

    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    sender_email = os.environ.get("BREVO_SENDER_EMAIL", "").strip()
    sender_name = os.environ.get("BREVO_SENDER_NAME", "Vela").strip() or "Vela"

    if api_key and sender_email:
        return BrevoProvider(api_key, sender_email, sender_name)

    logger.warning(
        "BREVO_API_KEY or BREVO_SENDER_EMAIL not set. Using console logging for alerts."
    )
    return ConsoleProvider()
