"""Structured API payloads when a registry blocks manifest lookup (401/403)."""

from __future__ import annotations

from typing import Any

from app.core.image_not_found_payload import IMAGE_NOT_FOUND_USER_MESSAGE

REGISTRY_ACCESS_DENIED_CODE = "registry_access_denied"


def registry_access_denied_api_content(
    image_ref: str,
    *,
    registry_detail: str | None = None,  # accepted for call-site compatibility; not exposed to clients
) -> dict[str, Any]:
    """Same user-facing message as a missing image; clients use HTTP status / error_code to distinguish."""
    return {
        "detail": IMAGE_NOT_FOUND_USER_MESSAGE,
        "error_code": REGISTRY_ACCESS_DENIED_CODE,
        "image_ref": image_ref,
    }
