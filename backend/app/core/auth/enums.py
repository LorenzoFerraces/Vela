from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    INSTRUCTOR = "instructor"
    STUDENT = "student"


def can_manage_users(role: UserRole | str) -> bool:
    return role in (UserRole.ADMIN, UserRole.INSTRUCTOR)


def is_admin(role: UserRole | str) -> bool:
    return role == UserRole.ADMIN
