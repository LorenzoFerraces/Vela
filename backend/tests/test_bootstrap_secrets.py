"""Fail-closed validation of deployment secrets at app startup."""

from __future__ import annotations

import pytest

from app.bootstrap_env import require_deployment_secrets


def test_require_deployment_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VELA_AUTH_SECRET", "")
    monkeypatch.setenv("VELA_TOKEN_ENCRYPTION_KEY", "   ")

    with pytest.raises(RuntimeError, match="Missing required secrets"):
        require_deployment_secrets()

    monkeypatch.setenv("VELA_AUTH_SECRET", "auth-secret")
    monkeypatch.setenv("VELA_TOKEN_ENCRYPTION_KEY", "encryption-key")
    require_deployment_secrets()
