import type { UserPublic } from '../api/client'

export function getUserInitials(user: Pick<UserPublic, 'display_name' | 'email'>): string {
  const displayName = user.display_name?.trim()
  if (displayName) {
    const parts = displayName.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) {
      return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase()
    }
    return displayName.slice(0, 2).toUpperCase()
  }
  const localPart = user.email.split('@')[0] ?? ''
  return localPart.slice(0, 2).toUpperCase() || '?'
}

export function getUserDisplayLabel(
  user: Pick<UserPublic, 'display_name' | 'email'>
): string {
  const displayName = user.display_name?.trim()
  if (displayName) return displayName
  return user.email
}
