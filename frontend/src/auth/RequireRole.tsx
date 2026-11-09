import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { isStaff } from './roles'

interface RequireStaffProps {
  children: ReactNode
}

export default function RequireStaff({ children }: RequireStaffProps) {
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

  if (!isStaff(user)) {
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}
