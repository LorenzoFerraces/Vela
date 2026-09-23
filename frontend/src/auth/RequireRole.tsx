import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import type { UserPublic } from '../api/client'
import { useAuth } from './AuthContext'
import { isAdmin, isStaff } from './roles'

interface RequireRoleProps {
  canAccess: (user: UserPublic | null) => boolean
  children: ReactNode
}

export function RequireRole({ canAccess, children }: RequireRoleProps) {
  const { status, user } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="auth-loading" role="status" aria-live="polite">
        <span className="skeleton skeleton--detail-title" />
      </div>
    )
  }

  if (status === 'anonymous') {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }

  if (!canAccess(user)) {
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}

export function RequireStaff({ children }: { children: ReactNode }) {
  return <RequireRole canAccess={isStaff}>{children}</RequireRole>
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  return <RequireRole canAccess={isAdmin}>{children}</RequireRole>
}

export default RequireStaff
