import type { UserPublic } from '../api/client'

export function isStaff(user: Pick<UserPublic, 'role'> | null): boolean {
  return user?.role === 'admin' || user?.role === 'instructor'
}

export function isAdmin(user: Pick<UserPublic, 'role'> | null): boolean {
  return user?.role === 'admin'
}

export function canManageTeams(user: Pick<UserPublic, 'role'> | null): boolean {
  return isStaff(user)
}

export function canViewGlobalAudit(
  user: Pick<UserPublic, 'role'> | null,
): boolean {
  return isAdmin(user)
}
