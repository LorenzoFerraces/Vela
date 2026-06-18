"""Object storage adapters for user-uploaded assets."""

from app.core.storage.memory import InMemoryObjectStorage
from app.core.storage.object_storage import ObjectStorage

__all__ = ["InMemoryObjectStorage", "ObjectStorage"]
