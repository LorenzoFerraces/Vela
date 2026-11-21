from enum import StrEnum


class UserRole(StrEnum):
    """Account roles: ADMIN, INSTRUCTOR, STUDENT."""
    ADMIN = "admin"
    INSTRUCTOR = "instructor"
    STUDENT = "student"


def can_manage_users(role: UserRole | str) -> bool:
    """True if the role may administer user accounts."""
    return role in (UserRole.ADMIN, UserRole.INSTRUCTOR)


def is_admin(role: UserRole | str) -> bool:
    """True if the role is ADMIN."""
    return role == UserRole.ADMIN
