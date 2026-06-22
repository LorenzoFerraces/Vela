"""Object storage adapters for user-uploaded assets."""

from app.core.storage.memory import InMemoryObjectStorage
from app.core.storage.object_storage import ObjectStorage
from app.core.storage.r2 import CloudflareR2ObjectStorage

__all__ = ["CloudflareR2ObjectStorage", "InMemoryObjectStorage", "ObjectStorage"]
