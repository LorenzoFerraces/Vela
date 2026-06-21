"""Project role helpers."""

from __future__ import annotations

from enum import StrEnum


class ProjectRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    VIEWER = "viewer"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


def can_read(role: ProjectRole | str) -> bool:
    return role in {ProjectRole.OWNER, ProjectRole.OPERATOR, ProjectRole.VIEWER}


def can_write(role: ProjectRole | str) -> bool:
    return role in {ProjectRole.OWNER, ProjectRole.OPERATOR}


def is_owner(role: ProjectRole | str) -> bool:
    return role == ProjectRole.OWNER
