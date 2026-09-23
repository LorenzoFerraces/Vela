import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createAdminUser,
  formatApiError,
  listAdminUsers,
  patchAdminUser,
} from '../../api/client'
import type { AdminUserCreate, AdminUserPublic, UserPublic } from '../../api/client'
import { isAdmin } from '../../auth/roles'
import { Skeleton } from '../../components/Skeleton'
import ConfirmDialog from '../../components/ConfirmDialog'
import CreateUserModal from './CreateUserModal'

const ROLE_OPTIONS: AdminUserPublic['role'][] = ['admin', 'instructor', 'student']
const STAFF_ROLE_OPTIONS: AdminUserPublic['role'][] = ['instructor', 'student']

type UsersPanelProps = {
  user: UserPublic | null
}

function isForbidden(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'status' in error && error.status === 403
}

function listErrorMessage(error: unknown): string {
  if (isForbidden(error)) {
    return 'User directory is admin-only. You can still create a student or instructor.'
  }
  return formatApiError(error)
}

function displayRole(role: AdminUserPublic['role']): string {
  return role[0].toUpperCase() + role.slice(1)
}

function displayDate(value: string): string {
  return new Date(value).toLocaleDateString([], {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export default function UsersPanel({ user }: UsersPanelProps) {
  const [users, setUsers] = useState<AdminUserPublic[]>([])
  const [total, setTotal] = useState(0)
  const [searchInput, setSearchInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [pendingDeactivate, setPendingDeactivate] = useState<AdminUserPublic | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const requestSeq = useRef(0)
  const canManage = isAdmin(user)
  const roleOptions = canManage ? ROLE_OPTIONS : STAFF_ROLE_OPTIONS
  const closeCreateModal = useCallback(() => setCreateOpen(false), [])

  const load = useCallback(async (query: string) => {
    const request = ++requestSeq.current
    setLoading(true)
    setError(null)
    try {
      const response = await listAdminUsers({ query: query || undefined, limit: 50 })
      if (request === requestSeq.current) {
        setUsers(response.users)
        setTotal(response.total)
      }
    } catch (loadError) {
      if (request === requestSeq.current) setError(listErrorMessage(loadError))
    } finally {
      if (request === requestSeq.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void load(searchInput.trim())
    }, 300)
    return () => window.clearTimeout(timeout)
  }, [load, searchInput, refreshKey])

  async function createUser(body: AdminUserCreate): Promise<void> {
    await createAdminUser(body)
    setCreateOpen(false)
    setNotice('User created')
    setRefreshKey((value) => value + 1)
  }

  async function updateUser(
    userId: string,
    body: { role?: AdminUserPublic['role']; is_active?: boolean },
    successMessage: string,
  ) {
    if (!canManage) return
    setError(null)
    setNotice(null)
    try {
      const updated = await patchAdminUser(userId, body)
      setUsers((current) => current.map((entry) => entry.id === updated.id ? updated : entry))
      setNotice(successMessage)
    } catch (updateError) {
      setError(formatApiError(updateError))
    }
  }

  async function deactivateUser() {
    if (!pendingDeactivate) return
    const target = pendingDeactivate
    setPendingDeactivate(null)
    await updateUser(target.id, { is_active: false }, 'User deactivated')
  }

  return (
    <section className="admin-users" aria-labelledby="admin-users-heading">
      <header className="admin-users__header">
        <div>
          <h2 id="admin-users-heading">Users</h2>
          <p className="admin-users__lead">Manage workspace access and roles.</p>
        </div>
        <button type="button" className="btn btn--primary" onClick={() => setCreateOpen(true)}>
          Create user
        </button>
      </header>

      <div className="admin-users__toolbar">
        <div className="settings-form__group">
          <label className="settings-form__label" htmlFor="admin-user-search">Search users</label>
          <input
            id="admin-user-search"
            className="settings-form__input"
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Email or name"
          />
        </div>
        <span className="admin-users__count">Showing {users.length} of {total}</span>
      </div>

      {error ? <p className="settings-banner settings-banner--err" role="alert">{error}</p> : null}
      {notice ? <p className="settings-banner settings-banner--ok" role="status">{notice}</p> : null}

      {loading ? (
        <div className="admin-users__table-wrap" aria-busy="true" aria-label="Loading users">
          <table className="admin-users__table">
            <thead>
              <tr><th>Email</th><th>Name</th><th>Role</th><th>Status</th><th>Created</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {Array.from({ length: 5 }).map((_, index) => (
                <tr key={index}><td colSpan={6}><Skeleton className="skeleton--team-row" /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : error && users.length === 0 ? null : users.length === 0 ? (
        <div className="admin-users__empty">No users match</div>
      ) : (
        <div className="admin-users__table-wrap">
          <table className="admin-users__table">
            <thead>
              <tr><th>Email</th><th>Name</th><th>Role</th><th>Status</th><th>Created</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {users.map((entry) => (
                <tr key={entry.id}>
                  <td>{entry.email}</td>
                  <td>{entry.display_name || '—'}</td>
                  <td>
                    {canManage ? (
                      <select
                        className="admin-users__role"
                        aria-label={`Role for ${entry.email}`}
                        value={entry.role}
                        onChange={(event) => {
                          void updateUser(entry.id, { role: event.target.value as AdminUserPublic['role'] }, 'Role updated')
                        }}
                      >
                        {roleOptions.map((role) => <option key={role} value={role}>{displayRole(role)}</option>)}
                      </select>
                    ) : displayRole(entry.role)}
                  </td>
                  <td>
                    <span className={`admin-users__status admin-users__status--${entry.is_active ? 'active' : 'inactive'}`}>
                      {entry.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>{displayDate(entry.created_at)}</td>
                  <td>
                    {canManage ? (
                      entry.is_active ? (
                        <button
                          type="button"
                          className="btn btn--danger btn--sm"
                          onClick={() => setPendingDeactivate(entry)}
                          aria-label={`Deactivate ${entry.email}`}
                        >
                          Deactivate
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          onClick={() => void updateUser(entry.id, { is_active: true }, 'User activated')}
                          aria-label={`Activate ${entry.email}`}
                        >
                          Activate
                        </button>
                      )
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={pendingDeactivate !== null}
        title="Deactivate user?"
        message={pendingDeactivate ? `${pendingDeactivate.email} will lose access.` : ''}
        confirmLabel="Deactivate"
        onConfirm={() => void deactivateUser()}
        onClose={() => setPendingDeactivate(null)}
      />
      <CreateUserModal
        open={createOpen}
        canCreateAdmin={canManage}
        onCancel={closeCreateModal}
        onCreate={createUser}
      />
    </section>
  )
}
