"""Shared naming helpers for organizations and workspaces."""

from __future__ import annotations

WORKSPACE_NAME_MAX_LENGTH = 320
WORKSPACE_SUFFIX = " workspace"


def personal_organization_name(email: str) -> str:
    normalized_email = email.strip()
    max_email_length = WORKSPACE_NAME_MAX_LENGTH - len(WORKSPACE_SUFFIX)
    if len(normalized_email) > max_email_length:
        normalized_email = normalized_email[:max_email_length]
    return f"{normalized_email}{WORKSPACE_SUFFIX}"
