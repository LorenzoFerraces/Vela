"""Profile read models (domain layer, not HTTP schemas)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UserProfileSnapshot:
    id: uuid.UUID
    email: str
    created_at: datetime
    display_name: str | None
    pronouns: str | None
    avatar_url: str | None
