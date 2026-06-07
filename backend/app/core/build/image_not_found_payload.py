"""Structured API payloads when a container image reference cannot be resolved."""

from __future__ import annotations

from typing import Any

IMAGE_NOT_FOUND_CODE = "image_not_found"

IMAGE_NOT_FOUND_USER_MESSAGE = "Image not found."


def image_not_found_api_content(
    image_ref: str,
    *,
    registry_detail: str | None = None,  # accepted for call-site compatibility; not exposed to clients
) -> dict[str, Any]:
    """Minimal JSON body for HTTP 404 and availability checks (no registry internals)."""
    return {
        "detail": IMAGE_NOT_FOUND_USER_MESSAGE,
        "error_code": IMAGE_NOT_FOUND_CODE,
        "image_ref": image_ref,
    }
