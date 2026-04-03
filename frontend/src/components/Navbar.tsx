import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/containers', label: 'Containers' },
  { to: '/builder', label: 'Builder' },
  { to: '/images', label: 'Images' },
  { to: '/settings', label: 'Settings' },
] as const

export default function Navbar() {
  return (
    <header className="navbar">
      <NavLink to="/" className="navbar__brand" end>
        <span className="navbar__logo" aria-hidden>
          ▲
        </span>
        <span className="navbar__title">Vela</span>
      </NavLink>
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
    </header>
  )
}
