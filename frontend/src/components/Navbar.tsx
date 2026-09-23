import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { MoonIcon } from '@phosphor-icons/react/Moon'
import { SunIcon } from '@phosphor-icons/react/Sun'
import { useTheme } from '../hooks/useTheme'
import UserMenu from './UserMenu'
import { VelaMarkIcon } from './VelaMarkIcon'

const navItems = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/containers', label: 'Containers' },
  { to: '/stacks', label: 'Stacks' },
  { to: '/builder', label: 'Builder' },
  { to: '/teams', label: 'Teams' },
] as const

export default function Navbar() {
  const { status, user, logout } = useAuth()
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()

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
      <button
        type="button"
        className="icon-btn"
        onClick={toggle}
        aria-label="Toggle color theme"
        aria-pressed={theme === 'light'}
      >
        {theme === 'light' ? (
          <MoonIcon size={14} weight="bold" aria-hidden />
        ) : (
          <SunIcon size={14} weight="bold" aria-hidden />
        )}
      </button>
      <div className="navbar__user">
        {isAuthenticated && user ? (
          <UserMenu user={user} onLogout={onLogout} />
        ) : status === 'anonymous' ? (
          <NavLink to="/login" className="navbar__link">
            Log in
          </NavLink>
        ) : null}
      </div>
    </header>
  )
}
