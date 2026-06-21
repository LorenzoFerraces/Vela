import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import UserAvatar from './UserAvatar'
import { getUserDisplayLabel } from '../utils/userDisplay'
import { VelaMarkIcon } from './VelaMarkIcon'

const navItems = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/containers', label: 'Containers' },
  { to: '/builder', label: 'Builder' },
  { to: '/teams', label: 'Teams' },
  { to: '/settings', label: 'Settings' },
] as const

export default function Navbar() {
  const { status, user, logout } = useAuth()
  const navigate = useNavigate()

  const isAuthenticated = status === 'authenticated'

  function onLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="navbar">
      <NavLink to="/" className="navbar__brand" end>
        <span className="vela-icon-box navbar__logo" aria-hidden>
          <VelaMarkIcon size={12} />
        </span>
        <span className="navbar__title">Vela</span>
      </NavLink>
      {isAuthenticated ? (
        <nav className="navbar__nav" aria-label="Main">
          <ul className="navbar__list">
            {navItems.map(({ to, label }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    `navbar__link${isActive ? ' navbar__link--active' : ''}`
                  }
                >
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      ) : (
        <span className="navbar__spacer" aria-hidden />
      )}
      <div className="navbar__user">
        {isAuthenticated && user ? (
          <>
            <UserAvatar user={user} className="navbar__avatar" size={28} />
            <span className="navbar__user-email" title={user.email}>
              {getUserDisplayLabel(user)}
            </span>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={onLogout}
            >
              Log out
            </button>
          </>
        ) : status === 'anonymous' ? (
          <NavLink to="/login" className="navbar__link">
            Log in
          </NavLink>
        ) : null}
      </div>
    </header>
  )
}
