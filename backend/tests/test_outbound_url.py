"""Outbound URL validation (SSRF guard)."""

from __future__ import annotations

import pytest

from app.core.security.outbound_url import (
    ALLOW_PRIVATE_ENV,
    validate_outbound_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.5/v1",
        "https://192.168.1.10/v1",
        "https://169.254.1.1/v1",
        "https://[::1]/v1",
        "https://[fd00::1]/v1",
        "https://localhost/v1",
    ],
)
def test_rejects_non_https_and_private_destinations(url: str) -> None:
    with pytest.raises(ValueError):
        validate_outbound_url(url)


def test_accepts_public_https() -> None:
    assert (
        validate_outbound_url("https://api.openai.com/v1")
        == "https://api.openai.com/v1"
    )


def test_allow_private_env_bypasses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOW_PRIVATE_ENV, "1")
    assert (
        validate_outbound_url("http://10.0.0.5:11434/v1")
        == "http://10.0.0.5:11434/v1"
    )
