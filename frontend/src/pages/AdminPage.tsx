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

  return (
    <section className="admin-page">
      <header className="admin-page__header">
        <h1 className="admin-page__title">[ ADMIN ]</h1>
        <p className="admin-page__lead">Workspace access, roles, and audit history.</p>
      </header>

      <div className="admin-tabs" role="tablist" aria-label="Admin sections">
        <button
          type="button"
          className={`admin-tabs__tab${activeTab === 'users' ? ' admin-tabs__tab--active' : ''}`}
          role="tab"
          aria-selected={activeTab === 'users'}
          aria-controls="admin-users-panel"
          onClick={() => setActiveTab('users')}
        >
          Users
        </button>
        {canViewAudit ? (
          <button
            type="button"
            className={`admin-tabs__tab${activeTab === 'audit' ? ' admin-tabs__tab--active' : ''}`}
            role="tab"
            aria-selected={activeTab === 'audit'}
            aria-controls="admin-audit-panel"
            onClick={() => setActiveTab('audit')}
          >
            Audit
          </button>
        ) : null}
      </div>

      <div
        id="admin-users-panel"
        role="tabpanel"
        hidden={activeTab !== 'users'}
      >
        {activeTab === 'users' ? <UsersPanel user={user} /> : null}
      </div>
      {canViewAudit ? (
        <div
          id="admin-audit-panel"
          role="tabpanel"
          hidden={activeTab !== 'audit'}
        >
          <AuditPanel active={activeTab === 'audit'} />
        </div>
      ) : null}
    </section>
  )
}
