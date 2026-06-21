"""Tests for Brevo email provider."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from brevo.core.api_error import ApiError

from app.core.notifications.email_provider import (
    BREVO_ALERT_TAG,
    BrevoProvider,
    EmailAlert,
    container_logs_attachment_filename,
    format_alert_email,
)


def test_format_alert_email() -> None:
    alert = EmailAlert(
        to="user@example.com",
        container_name="my-app",
        event_type="stop",
        timestamp=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        details="Container status: stopped",
    )
    subject, body = format_alert_email(alert)
    assert "my-app" in subject
    assert "STOP" in subject
    assert "Container status: stopped" in body


@pytest.mark.asyncio
async def test_brevo_provider_send_success() -> None:
    alert = EmailAlert(
        to="user@example.com",
        container_name="my-app",
        event_type="failure",
        timestamp=datetime.now(timezone.utc),
    )
    mock_client = MagicMock()
    mock_client.transactional_emails.send_transac_email = AsyncMock(
        return_value=MagicMock(message_id="201.abc@relay.domain.com")
    )
    provider = BrevoProvider(
        api_key="test-key",
        sender_email="alerts@example.com",
        sender_name="Vela",
        client=mock_client,
    )

    result = await provider.send_alert(alert)

    assert result is True
    call_kwargs = mock_client.transactional_emails.send_transac_email.await_args.kwargs
    assert call_kwargs["subject"]
    assert "my-app" in call_kwargs["subject"]
    assert call_kwargs["text_content"]
    assert call_kwargs["sender"].email == "alerts@example.com"
    assert call_kwargs["sender"].name == "Vela"
    assert len(call_kwargs["to"]) == 1
    assert call_kwargs["to"][0].email == "user@example.com"
    assert call_kwargs["tags"] == [BREVO_ALERT_TAG]
    assert "attachment" not in call_kwargs


@pytest.mark.asyncio
async def test_brevo_provider_send_with_log_attachment() -> None:
    alert = EmailAlert(
        to="user@example.com",
        container_name="my-app",
        event_type="failure",
        timestamp=datetime.now(timezone.utc),
        container_logs="error: process exited\n",
    )
    mock_client = MagicMock()
    mock_client.transactional_emails.send_transac_email = AsyncMock(
        return_value=MagicMock(message_id="201.abc@relay.domain.com")
    )
    provider = BrevoProvider(
        api_key="test-key",
        sender_email="alerts@example.com",
        client=mock_client,
    )

    result = await provider.send_alert(alert)

    assert result is True
    call_kwargs = mock_client.transactional_emails.send_transac_email.await_args.kwargs
    assert "Recent container logs are attached" in call_kwargs["text_content"]
    attachments = call_kwargs["attachment"]
    assert len(attachments) == 1
    assert attachments[0].name == container_logs_attachment_filename("my-app")
    assert attachments[0].content == base64.b64encode(
        b"error: process exited\n"
    ).decode("ascii")


@pytest.mark.asyncio
async def test_brevo_provider_send_api_error() -> None:
    mock_client = MagicMock()
    mock_client.transactional_emails.send_transac_email = AsyncMock(
        side_effect=ApiError(status_code=401, body={"message": "Unauthorized"})
    )
    provider = BrevoProvider(
        api_key="test-key",
        sender_email="alerts@example.com",
        client=mock_client,
    )
    alert = EmailAlert(
        to="user@example.com",
        container_name="my-app",
        event_type="stop",
        timestamp=datetime.now(timezone.utc),
    )

    result = await provider.send_alert(alert)

    assert result is False
