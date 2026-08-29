# Logs/Audit Nav + Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Logs and Audit Log from the top bar (account items move to a new user-menu dropdown) and redesign both pages (terminal-style log viewer, audit timeline), per `docs/superpowers/specs/2026-08-29-logs-audit-nav-redesign-design.md`.

**Architecture:** Frontend-only. A new `UserMenu` component turns the navbar's avatar cluster into a `role="menu"` dropdown (Settings / Audit Log / Log out). `LogsPage` gains a container `<select>` (from `listContainers()`), date-range filters, and a monospace terminal-style viewer. `AuditLogPage` gains a day-grouped timeline with action icons, a `container.exec` label, expandable `details` JSON, and date-range filters. All needed backend query params already exist — zero backend changes. Page CSS moves out of `index.css` into per-page files (precedent: `StacksPage.tsx` imports `./stacks/stacks.css`).

**Tech Stack:** React 19 + TypeScript, react-router-dom 7 (`useSearchParams`), `@phosphor-icons/react` 2.1.10 (already a dependency), Playwright E2E (`frontend/e2e/`), Vite, ESLint.

## Global Constraints

- **No backend changes.** `GET /api/logs/` already accepts `start_time`/`end_time`/`source`; `GET /api/audit/log` already accepts `from_date`/`to_date`; `listContainers()` exists at `frontend/src/api/client.ts:559`.
- **No new npm dependencies**; `package.json` versions stay exact (no `^`/`~`).
- **Design tokens**: no raw hex/rgba in TSX or inline styles. The log-level palette is the one documented exception (AGENTS.md) and lives in `pages/logs/logs.css`.
- **Focus**: never remove a focus outline without a visible replacement — use the 2px `var(--accent)` outline pattern.
- **Icons**: decorative Phosphor icons get `aria-hidden="true"`; menu items are `<button>`s with `role="menuitem"`.
- **Errors**: `role="alert"` with the existing `containers-banner containers-banner--err` classes.
- **CSS organization**: new page styles go in separate files imported by the page; `index.css` only gains the user-menu block, and the old `.logs-page__*` / `.audit-log-page__*` blocks are deleted (do not leave duplicates). The global `@media (prefers-reduced-motion: reduce)` block in `index.css` (~line 2439) already lists `.logs-page__skeleton-row::after` and `.audit-log-page__skeleton-row::after` — keep those class names so it keeps working.
- **Filters live in URL params** via `useSearchParams` with `{ replace: true }`; any filter change clears `offset`.
- **E2E**: drive the real SPA against the real API — no `page.route` mocking for app flows. Run single specs with `npm run test:e2e -- e2e/<file>.spec.ts` from `frontend/`; stop any dev server on ports 8000/5173 first (`reuseExistingServer` is off).
- **Verification after every task**: `npm run lint` and `npm run build` in `frontend/` must pass.
- Commit style (existing): `F/<area>: <imperative summary>` (e.g. `F/nav: user menu for settings, audit log, and logout`).

---

### Task 1: User menu in the navbar

**Files:**
- Create: `frontend/src/components/UserMenu.tsx`
- Modify: `frontend/src/components/Navbar.tsx` (whole file, 80 lines)
- Modify: `frontend/src/index.css` (add user-menu block after the `.navbar__avatar` / `.user-avatar--initials` block, ~line 686+)
- Test: `frontend/e2e/smoke.spec.ts` (rewrite)

**Interfaces:**
- Consumes: `useAuth()` → `{ status, user, logout }` (from `../auth/AuthContext`, as `Navbar.tsx` already uses); `UserAvatar` component (`./UserAvatar`, props `user`, `className?`, `size?`); `getUserDisplayLabel` from `../utils/userDisplay`; `UserPublic` type from `../api/client`.
- Produces: `<UserMenu user={user} onLogout={onLogout} />` — self-contained dropdown; `Navbar.tsx` renders exactly 5 nav links (Dashboard, Containers, Stacks, Builder, Teams) and the `Log in` link for anonymous visitors.

- [ ] **Step 1: Rewrite `frontend/e2e/smoke.spec.ts` (failing test first)**

```ts
import { appBase } from './constants'
import { expect, test } from './fixtures'

const baseURL = appBase

const protectedNavItems = [
  { label: 'Dashboard', path: '/dashboard', title: 'Dashboard' },
  { label: 'Containers', path: '/containers', title: 'Containers' },
  { label: 'Stacks', path: '/stacks', title: 'Stacks' },
  { label: 'Builder', path: '/builder', title: 'Builder' },
  { label: 'Teams', path: '/teams', title: 'Teams' },
] as const

// Display label of the seeded E2E user (display_name is null, so the email is shown).
const USER_MENU_TRIGGER = 'e2e@example.com'

test.describe('home page (anonymous)', () => {
  test('shows the Vela greeting and API health', async ({ page }) => {
    await page.goto('/')
    await expect(
      page.getByRole('heading', { name: 'Hola, esto es Vela' }),
    ).toBeVisible()
    await expect(page.getByText('API: ok')).toBeVisible()
  })

  test('navbar only offers a Log in entry point until you sign in', async ({
    page,
  }) => {
    await page.goto('/')
    await expect(
      page.getByRole('link', { name: 'Log in' }),
    ).toBeVisible()
    await expect(
      page.getByRole('navigation', { name: 'Main' }),
    ).toHaveCount(0)
  })
})

test.describe('navbar (authenticated)', () => {
  test('signed-in user can walk through every protected section', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/')

    const nav = authenticatedPage.getByRole('navigation', { name: 'Main' })
    await expect(nav.getByRole('link', { name: 'Logs' })).toHaveCount(0)
    await expect(nav.getByRole('link', { name: 'Audit Log' })).toHaveCount(0)

    for (const { label, path, title } of protectedNavItems) {
      await nav.getByRole('link', { name: label }).click()
      await expect(authenticatedPage).toHaveURL(`${baseURL}${path}`)
      await expect(
        authenticatedPage.getByRole('heading', { name: title, level: 1 }),
      ).toBeVisible()
      if (path === '/containers') {
        await expect(
          authenticatedPage.getByLabel('Deploy source'),
        ).toBeVisible()
      } else if (path === '/builder') {
        await expect(
          authenticatedPage.getByRole('heading', {
            name: 'Dockerfile templates',
            level: 2,
          }),
        ).toBeVisible()
      }
    }
  })

  test('user menu navigates to Settings', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/dashboard')
    await authenticatedPage
      .getByRole('button', { name: USER_MENU_TRIGGER })
      .click()
    const menu = authenticatedPage.getByRole('menu', { name: 'Account' })
    await expect(menu).toBeVisible()
    await menu.getByRole('menuitem', { name: 'Settings' }).click()
    await expect(authenticatedPage).toHaveURL(`${baseURL}/settings`)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Settings', level: 1 }),
    ).toBeVisible()
  })

  test('user menu navigates to Audit Log', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/dashboard')
    await authenticatedPage
      .getByRole('button', { name: USER_MENU_TRIGGER })
      .click()
    await authenticatedPage
      .getByRole('menuitem', { name: 'Audit Log' })
      .click()
    await expect(authenticatedPage).toHaveURL(`${baseURL}/audit`)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Audit Log', level: 1 }),
    ).toBeVisible()
  })

  test('signed-in user can log out through the user menu', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/dashboard')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Dashboard', level: 1 }),
    ).toBeVisible()

    await authenticatedPage
      .getByRole('button', { name: USER_MENU_TRIGGER })
      .click()
    await authenticatedPage.getByRole('menuitem', { name: 'Log out' }).click()
    await expect(authenticatedPage).toHaveURL(/\/login(\?.*)?$/)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Sign in to Vela' }),
    ).toBeVisible()
  })
})
```

- [ ] **Step 2: Run the smoke spec to verify it fails**

Run (from `frontend/`): `npm run test:e2e -- e2e/smoke.spec.ts`
Expected: FAIL — `Logs`/`Audit Log` links still exist in the nav (the `toHaveCount(0)` assertions fail), and the three user-menu tests fail because there is no button named `e2e@example.com` (the name is a plain span next to the old Log out button).

- [ ] **Step 3: Create `frontend/src/components/UserMenu.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  CaretDown,
  ClockCounterClockwise,
  GearSix,
  SignOut,
} from '@phosphor-icons/react'
import type { UserPublic } from '../api/client'
import { getUserDisplayLabel } from '../utils/userDisplay'
import UserAvatar from './UserAvatar'

type UserMenuProps = {
  user: UserPublic
  onLogout: () => void
}

export default function UserMenu({ user, onLogout }: UserMenuProps) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) {
      return
    }
    function onMouseDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('keydown', onKeyDown)
      triggerRef.current?.focus()
    }
  }, [open])

  function navigateTo(path: string) {
    setOpen(false)
    navigate(path)
  }

  function handleLogout() {
    setOpen(false)
    onLogout()
  }

  return (
    <div className="user-menu" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="user-menu__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        title={user.email}
        onClick={() => setOpen((previous) => !previous)}
      >
        <UserAvatar user={user} className="user-menu__avatar" size={28} />
        <span className="user-menu__label">{getUserDisplayLabel(user)}</span>
        <CaretDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className="user-menu__menu" role="menu" aria-label="Account">
          <button
            type="button"
            role="menuitem"
            className="user-menu__item"
            onClick={() => navigateTo('/settings')}
          >
            <GearSix size={16} aria-hidden="true" />
            Settings
          </button>
          <button
            type="button"
            role="menuitem"
            className="user-menu__item"
            onClick={() => navigateTo('/audit')}
          >
            <ClockCounterClockwise size={16} aria-hidden="true" />
            Audit Log
          </button>
          <div className="user-menu__divider" role="separator" />
          <button
            type="button"
            role="menuitem"
            className="user-menu__item user-menu__item--danger"
            onClick={handleLogout}
          >
            <SignOut size={16} aria-hidden="true" />
            Log out
          </button>
        </div>
      )}
    </div>
  )
}
```

Note: `UserMenu` does not call `useAuth()` itself — `Navbar` already owns `logout` + navigation (its `onLogout` does `logout(); navigate('/login', { replace: true })`), so the menu only takes the two props above.

- [ ] **Step 4: Rewrite `frontend/src/components/Navbar.tsx`**

```tsx
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
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
```

Removed imports: `UserAvatar`, `getUserDisplayLabel` (both now inside `UserMenu`).

- [ ] **Step 5: Add user-menu CSS to `frontend/src/index.css`**

Insert after the `.user-avatar--initials` block (which ends ~line 693), i.e. still inside the navbar section:

```css
.user-menu {
  position: relative;
  display: flex;
  align-items: center;
}

.user-menu__trigger {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.55rem;
  background: none;
  border: 1px solid transparent;
  border-radius: 8px;
  color: var(--text);
  font: inherit;
  font-size: 0.875rem;
  cursor: pointer;
}

.user-menu__trigger:hover {
  background: var(--bg-elevated);
  border-color: var(--border);
}

.user-menu__trigger:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.user-menu__avatar {
  flex-shrink: 0;
  border-radius: 50%;
  border: 1px solid var(--border);
}

.user-menu__label {
  max-width: 14rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
  font-size: 0.8125rem;
}

.user-menu__menu {
  position: absolute;
  top: calc(100% + 0.4rem);
  right: 0;
  z-index: 40;
  min-width: 11rem;
  padding: 0.3rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}

.user-menu__item {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: none;
  border: none;
  border-radius: 6px;
  color: var(--text);
  font: inherit;
  font-size: 0.875rem;
  text-align: left;
  cursor: pointer;
}

.user-menu__item:hover {
  background: var(--bg-deep);
}

.user-menu__item:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.user-menu__item--danger {
  color: var(--error);
}

.user-menu__divider {
  height: 1px;
  margin: 0.3rem 0;
  background: var(--border);
}
```

(`.navbar` is `z-index: 100` and sticky; the dropdown sits inside the header, so `z-index: 40` is relative to the header's stacking context and renders above page content.)

- [ ] **Step 6: Lint and build**

Run (from `frontend/`): `npm run lint` and `npm run build`
Expected: both pass. (tsc catches any prop/type mismatch between `UserMenu` and `Navbar`.)

- [ ] **Step 7: Run the smoke spec to verify it passes**

Run: `npm run test:e2e -- e2e/smoke.spec.ts`
Expected: PASS (all 5 tests).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/UserMenu.tsx frontend/src/components/Navbar.tsx frontend/src/index.css frontend/e2e/smoke.spec.ts
git commit -m "F/nav: user menu for settings, audit log, and logout"
```

---

### Task 2: Logs page redesign (picker, date range, terminal viewer)

**Files:**
- Create: `frontend/src/pages/logs/logs.css`
- Modify: `frontend/src/pages/LogsPage.tsx` (full rewrite)
- Modify: `frontend/src/index.css` (delete the `/* --- Logs page --- */` block — from that comment at ~line 3199 to end of file)
- Test: `frontend/e2e/logs.spec.ts` (rewrite)

**Interfaces:**
- Consumes (from `frontend/src/api/client.ts`, all pre-existing): `getLogs(params: LogQueryParams): Promise<LogQueryResponse>`; `exportLogs(params: Partial<LogQueryParams>): Promise<void>`; `listContainers(): Promise<ContainerInfo[]>`; `formatApiError(err): string`; types `LogEntry`, `LogQueryParams` (has optional `start_time`/`end_time` strings), `ContainerInfo` (`id`, `name`, `status`).
- Produces: `/logs` page. URL params: `container_id`, `level`, `q`, `start`, `end` (raw `datetime-local` values, e.g. `2026-08-29T14:30`), `offset`. The workloads-table link `to=/logs?container_id=<id>` must keep pre-selecting the picker (unchanged component — no edits there).

- [ ] **Step 1: Rewrite `frontend/e2e/logs.spec.ts` (failing test first)**

```ts
import { expect, test } from './fixtures'

test.describe('Logs page', () => {
  test('shows the container picker and empty state when no container is selected', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/logs')
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Logs', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('button', { name: 'Export CSV' }),
    ).toBeDisabled()
    await expect(
      authenticatedPage.getByRole('combobox', { name: 'Container' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByPlaceholder('Search logs…'),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByText('Select a container to view logs'),
    ).toBeVisible()
  })

  test('loads the log view for the container linked from the workloads table', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/containers')
    const sourceInput = authenticatedPage.getByLabel('Deploy source')
    await sourceInput.click()
    await sourceInput.fill('nginx')
    await authenticatedPage
      .getByRole('option', { name: 'nginx:alpine', exact: true })
      .click()
    await authenticatedPage.getByRole('button', { name: 'Build' }).click()
    await expect(
      authenticatedPage.getByRole('alert').filter({ hasText: 'Started' }),
    ).toBeVisible()

    await authenticatedPage.getByRole('link', { name: 'Logs' }).first().click()
    await expect(authenticatedPage).toHaveURL(/\/logs\?container_id=/)
    await expect(
      authenticatedPage.getByRole('combobox', { name: 'Container' }),
    ).toHaveValue(/.+/)
    await expect(
      authenticatedPage.getByText(/Showing \d+ of \d+ entries/),
    ).toBeVisible()
  })

  test('shows an error for an unknown container id in the URL', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/logs?container_id=nonexistent-id')
    await expect(authenticatedPage.getByRole('alert')).toBeVisible()
  })
})
```

- [ ] **Step 2: Run the logs spec to verify it fails**

Run: `npm run test:e2e -- e2e/logs.spec.ts`
Expected: FAIL — the page still has a "Container ID…" text input (no `combobox` named "Container", no disabled-state export button with the new empty state).

- [ ] **Step 3: Create `frontend/src/pages/logs/logs.css`**

```css
.logs-page__title {
  margin: 0 0 0.35rem;
  font-size: 1.75rem;
  font-weight: 600;
  color: var(--text-heading);
  text-wrap: balance;
}

.logs-page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.logs-page__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.logs-page__container-select,
.logs-page__filters .settings-form__input {
  max-width: 16rem;
}

.logs-page__search {
  flex: 1;
  min-width: 12rem;
  max-width: 20rem;
  padding: 0.55rem 0.75rem;
  font: inherit;
  font-size: 0.9375rem;
  color: var(--text-heading);
  background: var(--bg-deep);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.logs-page__search:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}

.logs-page__count {
  margin-bottom: 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-muted);
}

.logs-page__terminal {
  padding: 0.65rem 0.75rem;
  font-family: ui-monospace, 'Cascadia Code', monospace;
  font-size: 0.8125rem;
  line-height: 1.5;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.logs-page__line {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.15rem 0;
}

.logs-page__line-time {
  flex-shrink: 0;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.logs-page__line-level {
  flex-shrink: 0;
  width: 3.5rem;
  padding: 0.05rem 0.35rem;
  border-radius: 4px;
  text-align: center;
  font-size: 0.75rem;
  font-weight: 500;
}

/* ponytail: log-level palette is the documented token exception (AGENTS.md), kept with the page */
.logs-page__line-level--info {
  background: rgba(107, 114, 128, 0.12);
  color: #9aa5b4;
}

.logs-page__line-level--warn {
  background: rgba(232, 184, 74, 0.12);
  color: #e8b84a;
}

.logs-page__line-level--error {
  background: rgba(224, 112, 110, 0.12);
  color: #e0706e;
}

.logs-page__line-level--debug {
  background: rgba(122, 134, 153, 0.12);
  color: #7a8699;
}

.logs-page__line-source {
  flex-shrink: 0;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.logs-page__line-message {
  flex: 1;
  min-width: 0;
  color: var(--text);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.logs-page__empty {
  padding: 2rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.9375rem;
}

.logs-page__pagination {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.logs-page__skeleton {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.logs-page__skeleton-row {
  position: relative;
  height: 2rem;
  overflow: hidden;
  border-radius: 6px;
  background: var(--border);
}

.logs-page__skeleton-row::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.04) 50%,
    transparent
  );
  transform: translateX(-100%);
  animation: skeleton-shimmer 1.2s ease-in-out infinite;
}
```

- [ ] **Step 4: Rewrite `frontend/src/pages/LogsPage.tsx`**

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  exportLogs,
  formatApiError,
  getLogs,
  listContainers,
} from '../api/client'
import type { ContainerInfo, LogEntry, LogQueryParams } from '../api/client'
import './logs/logs.css'

const LIMIT = 100

function toIsoDateTime(raw: string): string {
  return new Date(raw).toISOString()
}

export default function LogsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [containers, setContainers] = useState<ContainerInfo[]>([])
  const fetchRequestRef = useRef(0)

  const search = searchParams.get('q') ?? ''
  const levelFilter = searchParams.get('level') ?? ''
  const containerFilter = searchParams.get('container_id') ?? ''
  const startRaw = searchParams.get('start') ?? ''
  const endRaw = searchParams.get('end') ?? ''
  const offsetParam = Number.parseInt(searchParams.get('offset') ?? '0', 10)
  const offset = Number.isNaN(offsetParam) ? 0 : offsetParam

  const hasContainer = containerFilter.trim().length > 0

  useEffect(() => {
    let active = true
    listContainers()
      .then((data) => {
        if (active) setContainers(data)
      })
      .catch(() => {
        // ponytail: picker stays empty on failure; URL-param container still works
      })
    return () => {
      active = false
    }
  }, [])

  function setFilterParam(name: string, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) {
      next.set(name, value)
    } else {
      next.delete(name)
    }
    next.delete('offset')
    setSearchParams(next, { replace: true })
  }

  function setOffsetParam(value: number) {
    const next = new URLSearchParams(searchParams)
    if (value > 0) {
      next.set('offset', String(value))
    } else {
      next.delete('offset')
    }
    setSearchParams(next, { replace: true })
  }

  const buildParams = useCallback(
    (includeOffset: boolean): LogQueryParams => {
      const params: LogQueryParams = {
        container_id: containerFilter.trim(),
        limit: LIMIT,
      }
      if (includeOffset) params.offset = offset
      if (search) params.q = search
      if (levelFilter) params.level = levelFilter
      if (startRaw) params.start_time = toIsoDateTime(startRaw)
      if (endRaw) params.end_time = toIsoDateTime(endRaw)
      return params
    },
    [search, levelFilter, containerFilter, startRaw, endRaw, offset],
  )

  const fetchLogs = useCallback(async () => {
    const requestId = fetchRequestRef.current + 1
    fetchRequestRef.current = requestId
    try {
      const res = await getLogs(buildParams(true))
      if (fetchRequestRef.current === requestId) {
        setEntries(res.entries)
        setTotal(res.total)
        setError(null)
      }
    } catch (err) {
      if (fetchRequestRef.current === requestId) {
        setError(formatApiError(err))
      }
    } finally {
      if (fetchRequestRef.current === requestId) {
        setLoading(false)
      }
    }
  }, [buildParams])

  useEffect(() => {
    if (!hasContainer) return
    fetchLogs()
  }, [hasContainer, fetchLogs])

  const handleExport = async () => {
    if (!hasContainer) return
    try {
      await exportLogs(buildParams(false))
    } catch (err) {
      setError(formatApiError(err))
    }
  }

  const knownContainer = containers.some(
    (container) => container.id === containerFilter,
  )

  function onFilterChange(name: string, value: string) {
    setFilterParam(name, value)
    setEntries([])
    setLoading(true)
  }

  function onOffsetChange(value: number) {
    setOffsetParam(value)
    setEntries([])
    setLoading(true)
  }

  return (
    <section className="logs-page">
      <div className="logs-page__header">
        <h1 className="logs-page__title">Logs</h1>
        <button
          type="button"
          onClick={handleExport}
          disabled={!hasContainer}
          className="btn btn--ghost btn--sm"
        >
          Export CSV
        </button>
      </div>

      {hasContainer && error ? (
        <div className="containers-banner containers-banner--err" role="alert">
          <p className="containers-banner__text">{error}</p>
        </div>
      ) : null}

      <div className="logs-page__filters">
        <select
          aria-label="Container"
          className="settings-form__input logs-page__container-select"
          value={containerFilter}
          onChange={(e) => onFilterChange('container_id', e.target.value)}
        >
          <option value="">Select a container…</option>
          {containerFilter && !knownContainer ? (
            <option value={containerFilter}>
              {containerFilter.slice(0, 8)}
            </option>
          ) : null}
          {containers.map((container) => (
            <option key={container.id} value={container.id}>
              {container.name || container.id.slice(0, 8)} (
              {container.status})
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by level"
          className="settings-form__input"
          value={levelFilter}
          onChange={(e) => onFilterChange('level', e.target.value)}
        >
          <option value="">All levels</option>
          <option value="info">Info</option>
          <option value="warn">Warn</option>
          <option value="error">Error</option>
          <option value="debug">Debug</option>
        </select>
        <input
          type="datetime-local"
          aria-label="From"
          className="settings-form__input"
          value={startRaw}
          onChange={(e) => onFilterChange('start', e.target.value)}
        />
        <input
          type="datetime-local"
          aria-label="To"
          className="settings-form__input"
          value={endRaw}
          onChange={(e) => onFilterChange('end', e.target.value)}
        />
        <input
          type="text"
          aria-label="Search logs"
          autoComplete="off"
          placeholder="Search logs…"
          className="logs-page__search"
          value={search}
          onChange={(e) => onFilterChange('q', e.target.value)}
        />
      </div>

      {!hasContainer ? (
        <div className="logs-page__empty">
          Select a container to view logs
        </div>
      ) : loading ? (
        <div className="logs-page__skeleton">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="logs-page__skeleton-row" />
          ))}
        </div>
      ) : (
        <>
          <div className="logs-page__count">
            Showing {entries.length} of {total} entries
          </div>
          <div
            className="logs-page__terminal"
            role="log"
            aria-label="Log entries"
          >
            {entries.map((entry, index) => (
              <div
                key={`${entry.timestamp}-${index}`}
                className="logs-page__line"
              >
                <span className="logs-page__line-time">
                  {new Date(entry.timestamp).toLocaleString([], {
                    hour12: false,
                  })}
                </span>
                <span
                  className={`logs-page__line-level logs-page__line-level--${entry.level}`}
                >
                  {entry.level}
                </span>
                <span className="logs-page__line-source">
                  {entry.source}
                </span>
                <span className="logs-page__line-message">
                  {entry.message}
                </span>
              </div>
            ))}
            {entries.length === 0 && (
              <div className="logs-page__empty">No logs found</div>
            )}
          </div>
          <div className="logs-page__pagination">
            {offset > 0 && (
              <button
                type="button"
                onClick={() => onOffsetChange(offset - LIMIT)}
                className="btn btn--ghost btn--sm"
              >
                Previous
              </button>
            )}
            {offset + LIMIT < total && (
              <button
                type="button"
                onClick={() => onOffsetChange(offset + LIMIT)}
                className="btn btn--ghost btn--sm"
              >
                Next
              </button>
            )}
          </div>
        </>
      )}
    </section>
  )
}
```

The `knownContainer` fallback `<option>` keeps the select valid when the URL carries a container id that is no longer in `listContainers()` (deleted container whose logs are still within retention, or direct navigation) — the fetch then surfaces the backend's "Container not found" error banner.

- [ ] **Step 5: Delete the old logs CSS from `frontend/src/index.css`**

Remove everything from the `/* --- Logs page --- */` comment (~line 3199) to the end of the file (the file currently ends inside that block). Keep the `/* --- Audit log page --- */` block above it (Task 3 removes it).

- [ ] **Step 6: Lint and build**

Run (from `frontend/`): `npm run lint` and `npm run build`
Expected: both pass.

- [ ] **Step 7: Run the logs spec to verify it passes**

Run: `npm run test:e2e -- e2e/logs.spec.ts`
Expected: PASS (all 3 tests).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/LogsPage.tsx frontend/src/pages/logs/logs.css frontend/src/index.css frontend/e2e/logs.spec.ts
git commit -m "F/logs: container picker, date range, and terminal-style viewer"
```

---

### Task 3: Audit page redesign (timeline, exec label, details, date range)

**Files:**
- Create: `frontend/src/pages/audit/audit.css`
- Modify: `frontend/src/pages/AuditLogPage.tsx` (full rewrite)
- Modify: `frontend/src/index.css` (delete the `/* --- Audit log page --- */` block, ~lines 3083-3197)
- Test: `frontend/e2e/audit.spec.ts` (new)

**Interfaces:**
- Consumes (from `frontend/src/api/client.ts`, all pre-existing): `getAuditLog(params: AuditLogQueryParams): Promise<AuditLogResponse>` (params include `from_date`/`to_date` ISO strings); `formatApiError`; types `AuditLogEntry` (`id`, `action`, `target_type`, `target_id`, `details: Record<string, unknown> | null`, `created_at`), `AuditLogQueryParams`.
- Produces: `/audit` page reachable from the Task 1 user menu. URL params: `action`, `target`, `from`, `to` (raw `date` values, e.g. `2026-08-29`), `offset`.

- [ ] **Step 1: Create `frontend/e2e/audit.spec.ts` (failing test first)**

```ts
import { expect, test } from './fixtures'

test.describe('Audit log page', () => {
  test('opens from the user menu and shows filters and entry state', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/dashboard')
    await authenticatedPage
      .getByRole('button', { name: 'e2e@example.com' })
      .click()
    await authenticatedPage
      .getByRole('menuitem', { name: 'Audit Log' })
      .click()

    await expect(authenticatedPage).toHaveURL(/\/audit/)
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Audit Log', level: 1 }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('combobox', { name: 'Filter by action' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByRole('combobox', { name: 'Filter by target type' }),
    ).toBeVisible()
    await expect(
      authenticatedPage.getByLabel('From date'),
    ).toBeVisible()
    await expect(
      authenticatedPage
        .getByText(/Showing \d+ of \d+ entries|No audit entries found/)
        .first(),
    ).toBeVisible()
  })
})
```

Note: the seeded E2E user may or may not have audit rows at this point (other specs deploy containers against the shared E2E DB), so the test accepts either the count line or the empty state — it must not assert emptiness. The `From date` input assertion is what makes the spec fail against the current page.

- [ ] **Step 2: Run the audit spec to verify it fails**

Run: `npm run test:e2e -- e2e/audit.spec.ts`
Expected: FAIL — no input labelled "From date" exists on the current page.

- [ ] **Step 3: Create `frontend/src/pages/audit/audit.css`**

```css
.audit-log-page__title {
  margin: 0 0 0.35rem;
  font-size: 1.75rem;
  font-weight: 600;
  color: var(--text-heading);
  text-wrap: balance;
}

.audit-log-page__lead {
  margin: 0 0 1.25rem;
  color: var(--text-muted);
  font-size: 0.9375rem;
}

.audit-log-page__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.audit-log-page__filters .settings-form__input {
  max-width: 14rem;
}

.audit-log-page__count {
  margin-bottom: 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-muted);
}

.audit-log-page__timeline {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
}

.audit-log-page__day {
  border-bottom: 1px solid var(--border);
}

.audit-log-page__day:last-child {
  border-bottom: none;
}

.audit-log-page__day-label {
  margin: 0;
  padding: 0.45rem 0.85rem;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
  background: var(--bg-deep);
  border-bottom: 1px solid var(--border);
}

.audit-log-page__row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 0.85rem;
  font-size: 0.875rem;
}

.audit-log-page__icon {
  flex-shrink: 0;
  color: var(--text-muted);
}

.audit-log-page__sentence {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-log-page__target-id {
  font-family: ui-monospace, monospace;
  font-size: 0.8125rem;
  background: var(--bg-deep);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0 0.3rem;
}

.audit-log-page__time {
  flex-shrink: 0;
  font-size: 0.8125rem;
  color: var(--text-muted);
}

.audit-log-page__details {
  flex-shrink: 0;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.audit-log-page__details summary {
  cursor: pointer;
}

.audit-log-page__details summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.audit-log-page__details pre {
  margin: 0.35rem 0 0;
  padding: 0.5rem 0.6rem;
  max-width: 20rem;
  overflow: auto;
  font-size: 0.75rem;
  background: var(--bg-deep);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.audit-log-page__empty {
  padding: 2rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.9375rem;
}

.audit-log-page__pagination {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.audit-log-page__skeleton {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.audit-log-page__skeleton-row {
  position: relative;
  height: 2.25rem;
  overflow: hidden;
  border-radius: 6px;
  background: var(--border);
}

.audit-log-page__skeleton-row::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.04) 50%,
    transparent
  );
  transform: translateX(-100%);
  animation: skeleton-shimmer 1.2s ease-in-out infinite;
}
```

- [ ] **Step 4: Rewrite `frontend/src/pages/AuditLogPage.tsx`**

```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowClockwise,
  DotsThree,
  IdentificationBadge,
  Play,
  RocketLaunch,
  Stop,
  TerminalWindow,
  Trash,
  UserCircle,
} from '@phosphor-icons/react'
import { formatApiError, getAuditLog } from '../api/client'
import type {
  AuditLogEntry,
  AuditLogQueryParams,
} from '../api/client'
import './audit/audit.css'

const LIMIT = 50

type ActionMeta = {
  label: string
  sentence: string
  Icon: typeof Play
}

const ACTION_META: Record<string, ActionMeta> = {
  'container.deploy': {
    label: 'Deploy',
    sentence: 'Deployed container',
    Icon: RocketLaunch,
  },
  'container.start': {
    label: 'Start',
    sentence: 'Started container',
    Icon: Play,
  },
  'container.stop': {
    label: 'Stop',
    sentence: 'Stopped container',
    Icon: Stop,
  },
  'container.restart': {
    label: 'Restart',
    sentence: 'Restarted container',
    Icon: ArrowClockwise,
  },
  'container.remove': {
    label: 'Remove',
    sentence: 'Removed container',
    Icon: Trash,
  },
  'container.exec': {
    label: 'Exec',
    sentence: 'Ran command in container',
    Icon: TerminalWindow,
  },
  'user.profile_update': {
    label: 'Profile update',
    sentence: 'Updated profile',
    Icon: IdentificationBadge,
  },
  'user.avatar_upload': {
    label: 'Avatar upload',
    sentence: 'Uploaded avatar',
    Icon: UserCircle,
  },
  'user.avatar_removed': {
    label: 'Avatar removed',
    sentence: 'Removed avatar',
    Icon: UserCircle,
  },
}

const FALLBACK_META: ActionMeta = {
  label: '',
  sentence: 'Performed action',
  Icon: DotsThree,
}

type DayGroup = {
  key: string
  label: string
  entries: AuditLogEntry[]
}

function dayLabel(date: Date, now: Date): string {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const diffDays = Math.round((today.getTime() - day.getTime()) / 86_400_000)
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  return date.toLocaleDateString([], {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function groupByDay(entries: AuditLogEntry[]): DayGroup[] {
  const now = new Date()
  const groups: DayGroup[] = []
  for (const entry of entries) {
    const date = new Date(entry.created_at)
    const key = date.toDateString()
    const last = groups[groups.length - 1]
    if (last && last.key === key) {
      last.entries.push(entry)
    } else {
      groups.push({ key, label: dayLabel(date, now), entries: [entry] })
    }
  }
  return groups
}

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [searchParams, setSearchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const requestSeq = useRef(0)

  const actionFilter = searchParams.get('action') ?? ''
  const targetTypeFilter = searchParams.get('target') ?? ''
  const fromRaw = searchParams.get('from') ?? ''
  const toRaw = searchParams.get('to') ?? ''
  const offsetParam = Number.parseInt(searchParams.get('offset') ?? '0', 10)
  const offset = Number.isNaN(offsetParam) ? 0 : offsetParam

  function setFilterParam(name: string, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) {
      next.set(name, value)
    } else {
      next.delete(name)
    }
    next.delete('offset')
    setSearchParams(next, { replace: true })
  }

  function setOffsetParam(value: number) {
    const next = new URLSearchParams(searchParams)
    if (value > 0) {
      next.set('offset', String(value))
    } else {
      next.delete('offset')
    }
    setSearchParams(next, { replace: true })
  }

  const filterParams = useMemo<AuditLogQueryParams>(() => {
    const params: AuditLogQueryParams = { limit: LIMIT, offset }
    if (actionFilter) params.action = actionFilter
    if (targetTypeFilter) params.target_type = targetTypeFilter
    if (fromRaw) params.from_date = new Date(`${fromRaw}T00:00:00`).toISOString()
    if (toRaw) params.to_date = new Date(`${toRaw}T23:59:59`).toISOString()
    return params
  }, [actionFilter, targetTypeFilter, fromRaw, toRaw, offset])

  const load = useCallback(async (params: AuditLogQueryParams) => {
    const seq = ++requestSeq.current
    setLoading(true)
    setError(null)
    try {
      const data = await getAuditLog(params)
      if (seq === requestSeq.current) {
        setEntries(data.entries)
        setTotal(data.total)
      }
    } catch (err) {
      if (seq === requestSeq.current) setError(formatApiError(err))
    } finally {
      if (seq === requestSeq.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(filterParams)
  }, [load, filterParams])

  const groups = useMemo(() => groupByDay(entries), [entries])

  return (
    <section className="audit-log-page">
      <h1 className="audit-log-page__title">Audit Log</h1>
      <p className="audit-log-page__lead">
        History of actions performed in your account.
      </p>

      {error ? (
        <div className="containers-banner containers-banner--err" role="alert">
          <p className="containers-banner__text">{error}</p>
        </div>
      ) : null}

      <div className="audit-log-page__filters">
        <select
          aria-label="Filter by action"
          className="settings-form__input"
          value={actionFilter}
          onChange={(e) => setFilterParam('action', e.target.value)}
        >
          <option value="">All actions</option>
          {Object.entries(ACTION_META).map(([value, meta]) => (
            <option key={value} value={value}>
              {meta.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by target type"
          className="settings-form__input"
          value={targetTypeFilter}
          onChange={(e) => setFilterParam('target', e.target.value)}
        >
          <option value="">All targets</option>
          <option value="container">Containers</option>
          <option value="user">Users</option>
        </select>
        <input
          type="date"
          aria-label="From date"
          className="settings-form__input"
          value={fromRaw}
          onChange={(e) => setFilterParam('from', e.target.value)}
        />
        <input
          type="date"
          aria-label="To date"
          className="settings-form__input"
          value={toRaw}
          onChange={(e) => setFilterParam('to', e.target.value)}
        />
      </div>

      {loading ? (
        <div className="audit-log-page__skeleton">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="audit-log-page__skeleton-row" />
          ))}
        </div>
      ) : (
        <>
          <div className="audit-log-page__count">
            Showing {entries.length} of {total} entries
          </div>
          <div className="audit-log-page__timeline">
            {groups.map((group) => (
              <div key={group.key} className="audit-log-page__day">
                <h2 className="audit-log-page__day-label">{group.label}</h2>
                {group.entries.map((entry) => {
                  const meta = ACTION_META[entry.action] ?? {
                    ...FALLBACK_META,
                    label: entry.action,
                  }
                  const Icon = meta.Icon
                  const isSelf = entry.target_type === 'user'
                  return (
                    <div key={entry.id} className="audit-log-page__row">
                      <Icon
                        size={16}
                        className="audit-log-page__icon"
                        aria-hidden="true"
                      />
                      <span className="audit-log-page__sentence">
                        {meta.sentence}
                        {!isSelf ? (
                          <>
                            {' '}
                            <code className="audit-log-page__target-id">
                              {entry.target_id.slice(0, 8)}
                            </code>
                          </>
                        ) : null}
                      </span>
                      <span className="audit-log-page__time">
                        {new Date(entry.created_at).toLocaleString([], {
                          hour12: false,
                        })}
                      </span>
                      {entry.details ? (
                        <details className="audit-log-page__details">
                          <summary>Details</summary>
                          <pre>{JSON.stringify(entry.details, null, 2)}</pre>
                        </details>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            ))}
            {entries.length === 0 && (
              <div className="audit-log-page__empty">
                No audit entries found
              </div>
            )}
          </div>
          <div className="audit-log-page__pagination">
            {offset > 0 && (
              <button
                type="button"
                onClick={() => setOffsetParam(offset - LIMIT)}
                className="btn btn--ghost btn--sm"
              >
                Previous
              </button>
            )}
            {offset + LIMIT < total && (
              <button
                type="button"
                onClick={() => setOffsetParam(offset + LIMIT)}
                className="btn btn--ghost btn--sm"
              >
                Next
              </button>
            )}
          </div>
        </>
      )}
    </section>
  )
}
```

- [ ] **Step 5: Delete the old audit CSS from `frontend/src/index.css`**

Remove the `/* --- Audit log page --- */` block (~lines 3083-3197, i.e. from that comment up to just before the next section comment). After Task 2 the file's remaining tail is this block only — delete through end of file.

- [ ] **Step 6: Lint and build**

Run (from `frontend/`): `npm run lint` and `npm run build`
Expected: both pass.

- [ ] **Step 7: Run the audit spec to verify it passes**

Run: `npm run test:e2e -- e2e/audit.spec.ts`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/AuditLogPage.tsx frontend/src/pages/audit/audit.css frontend/src/index.css frontend/e2e/audit.spec.ts
git commit -m "F/audit: day-grouped timeline with exec label, details, date range"
```

---

### Task 4: Full verification and docs commit

**Files:**
- None modified (verification only); commits `docs/superpowers/specs/2026-08-29-logs-audit-nav-redesign-design.md` and this plan file.

- [ ] **Step 1: Backend suite (must stay green — no backend changes)**

Run (from `backend/`): `python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 2: Frontend lint and production build**

Run (from `frontend/`): `npm run lint` and `npm run build`
Expected: both pass.

- [ ] **Step 3: Full E2E suite**

Ensure nothing is running on ports 8000/5173, then run (from `frontend/`): `npm run test:e2e`
Expected: full suite passes (including the untouched `settings`, `stacks`, `builder`, `dashboard`, `auth` specs — they navigate via `page.goto`, so they are unaffected).

- [ ] **Step 4: Commit the design docs**

```bash
git add docs/superpowers/specs/2026-08-29-logs-audit-nav-redesign-design.md docs/superpowers/plans/2026-08-29-logs-audit-nav-redesign.md
git commit -m "F/docs: logs/audit nav redesign spec and plan"
```
