"""In-memory object storage for tests and local dev without R2 credentials."""

from __future__ import annotations

from urllib.parse import urlencode

from app.core.storage.object_storage import ObjectStorage


class InMemoryObjectStorage(ObjectStorage):
    """Dict-backed store with synthetic public URLs."""

    def __init__(self, *, public_base_url: str = "https://storage.test") -> None:
        self._public_base_url = public_base_url.rstrip("/")
        self._objects: dict[str, tuple[bytes, str]] = {}

    async def put_object(
        self, *, key: str, body: bytes, content_type: str
    ) -> None:
        self._objects[key] = (body, content_type)

    async def delete_object(self, *, key: str) -> None:
        self._objects.pop(key, None)

    def public_url(self, *, key: str, cache_bust: str | None = None) -> str:
        base = f"{self._public_base_url}/{key.lstrip('/')}"
        if cache_bust is None:
            return base
        query = urlencode({"v": cache_bust})
        return f"{base}?{query}"

    def get_object(self, key: str) -> tuple[bytes, str] | None:
        """Test helper: return stored body and content type."""
        return self._objects.get(key)

    def object_keys(self) -> list[str]:
        """Test helper: list stored keys."""
        return list(self._objects.keys())
