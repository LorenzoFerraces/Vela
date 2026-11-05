import { useEffect, useId, useRef, useState } from 'react'
import { formatApiError } from '../../api/client'
import type { AdminUserCreate } from '../../api/client'

const ALL_ROLES: AdminUserCreate['role'][] = ['admin', 'instructor', 'student']
const STAFF_ROLES: AdminUserCreate['role'][] = ['instructor', 'student']

type CreateUserModalProps = {
  open: boolean
  canCreateAdmin: boolean
  onCancel: () => void
  onCreate: (body: AdminUserCreate) => Promise<void>
}

export default function CreateUserModal({
  open,
  canCreateAdmin,
  onCancel,
  onCreate,
}: CreateUserModalProps) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<AdminUserCreate['role']>('student')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const roles = canCreateAdmin ? ALL_ROLES : STAFF_ROLES

  useEffect(() => {
    if (!open) return
    setEmail('')
    setPassword('')
    setDisplayName('')
    setRole('student')
    setError(null)
    setBusy(false)
  }, [open])

  useEffect(() => {
    if (!open) return
    const previouslyFocused = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCancel()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      previouslyFocused?.focus()
    }
  }, [open, onCancel])

  if (!open) return null

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onCreate({
        email: email.trim(),
        password,
        display_name: displayName.trim() || null,
        role,
      })
    } catch (createError) {
      setError(formatApiError(createError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stacks-modal-backdrop" role="presentation" onClick={busy ? undefined : onCancel}>
      <div
        ref={dialogRef}
        className="stacks-modal stacks-modal--build-config"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="stacks-modal__header">
          <h2 id={titleId} className="stacks-modal__title">Create user</h2>
          <p className="stacks-modal__lead">Add a user to the Vela workspace.</p>
        </header>

        <form className="admin-user-form" onSubmit={handleSubmit}>
          <div className="settings-form__group">
            <label className="settings-form__label" htmlFor="admin-create-email">Email</label>
            <input
              id="admin-create-email"
              className="settings-form__input"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
              disabled={busy}
            />
          </div>
          <div className="settings-form__group">
            <label className="settings-form__label" htmlFor="admin-create-password">Password</label>
            <input
              id="admin-create-password"
              className="settings-form__input"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
              disabled={busy}
            />
          </div>
          <div className="settings-form__group">
            <label className="settings-form__label" htmlFor="admin-create-name">Display name (optional)</label>
            <input
              id="admin-create-name"
              className="settings-form__input"
              type="text"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              maxLength={120}
              disabled={busy}
            />
          </div>
          <div className="settings-form__group">
            <label className="settings-form__label" htmlFor="admin-create-role">Role</label>
            <select
              id="admin-create-role"
              className="settings-form__input"
              value={role}
              onChange={(event) => setRole(event.target.value as AdminUserCreate['role'])}
              disabled={busy}
            >
              {roles.map((option) => (
                <option key={option} value={option}>
                  {option[0].toUpperCase() + option.slice(1)}
                </option>
              ))}
            </select>
          </div>
          {error ? <p className="settings-banner settings-banner--err" role="alert">{error}</p> : null}
          <footer className="stacks-modal__footer">
            <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              {busy ? 'Creating…' : 'Create user'}
            </button>
          </footer>
        </form>
      </div>
    </div>
  )
}
