"""Provider-agnostic object storage interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ObjectStorage(ABC):
    """Abstract blob store (Cloudflare R2, S3, in-memory for tests, etc.)."""

    @abstractmethod
    async def put_object(
        self, *, key: str, body: bytes, content_type: str
    ) -> None:
        """Store an object at the given key."""

    @abstractmethod
    async def delete_object(self, *, key: str) -> None:
        """Remove an object. Missing keys are ignored where the provider allows."""

    @abstractmethod
    def public_url(self, *, key: str, cache_bust: str | None = None) -> str:
        """Return the public URL for an object key."""
