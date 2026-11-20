import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { isAdmin } from '../auth/roles'
import AuditPanel from './admin/AuditPanel'
import UsersPanel from './admin/UsersPanel'
import './admin/admin.css'

type AdminTab = 'users' | 'audit'

export default function AdminPage() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState<AdminTab>('users')
  const canViewAudit = isAdmin(user)
  const tabs: AdminTab[] = canViewAudit ? ['users', 'audit'] : ['users']

  function onTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const index = tabs.indexOf(activeTab)
    const delta = event.key === 'ArrowRight' ? 1 : -1
    const next = tabs[(index + delta + tabs.length) % tabs.length]
    setActiveTab(next)
    document.getElementById(`admin-${next}-tab`)?.focus()
  }

  return (
    <section className="admin-page">
      <header className="admin-page__header">
        <h1 className="admin-page__title">[ ADMIN ]</h1>
        <p className="admin-page__lead">Workspace access, roles, and audit history.</p>
      </header>

      <div className="admin-tabs" role="tablist" aria-label="Admin sections">
        <button
          type="button"
          id="admin-users-tab"
          className={`admin-tabs__tab${activeTab === 'users' ? ' admin-tabs__tab--active' : ''}`}
          role="tab"
          aria-selected={activeTab === 'users'}
          aria-controls="admin-users-panel"
          tabIndex={activeTab === 'users' ? 0 : -1}
          onClick={() => setActiveTab('users')}
          onKeyDown={onTabKeyDown}
        >
          Users
        </button>
        {canViewAudit ? (
          <button
            type="button"
            id="admin-audit-tab"
            className={`admin-tabs__tab${activeTab === 'audit' ? ' admin-tabs__tab--active' : ''}`}
            role="tab"
            aria-selected={activeTab === 'audit'}
            aria-controls="admin-audit-panel"
            tabIndex={activeTab === 'audit' ? 0 : -1}
            onClick={() => setActiveTab('audit')}
            onKeyDown={onTabKeyDown}
          >
            Audit
          </button>
        ) : null}
      </div>

      <div
        id="admin-users-panel"
        role="tabpanel"
        aria-labelledby="admin-users-tab"
        hidden={activeTab !== 'users'}
      >
        {activeTab === 'users' ? <UsersPanel user={user} /> : null}
      </div>
      {canViewAudit ? (
        <div
          id="admin-audit-panel"
          role="tabpanel"
          aria-labelledby="admin-audit-tab"
          hidden={activeTab !== 'audit'}
        >
          <AuditPanel active={activeTab === 'audit'} />
        </div>
      ) : null}
    </section>
  )
}
