import { useCallback, useEffect, useState } from 'react'
import { formatApiError, getAuditLog } from '../api/client'
import type { AuditLogEntry } from '../api/client'

const LIMIT = 50

const ACTION_LABELS: Record<string, string> = {
  'container.deploy': 'Deploy',
  'container.start': 'Start',
  'container.stop': 'Stop',
  'container.restart': 'Restart',
  'container.remove': 'Remove',
  'user.profile_update': 'Profile update',
  'user.avatar_upload': 'Avatar upload',
  'user.avatar_removed': 'Avatar removed',
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [actionFilter, setActionFilter] = useState('')
  const [targetTypeFilter, setTargetTypeFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [reqSeq, setReqSeq] = useState(0)

  const fetchAuditLog = useCallback(async () => {
    const seq = reqSeq + 1
    setReqSeq(seq)
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string | number> = { limit: LIMIT, offset }
      if (actionFilter) params.action = actionFilter
      if (targetTypeFilter) params.target_type = targetTypeFilter
      const res = await getAuditLog(params as any)
      if (seq === reqSeq) {
        setEntries(res.entries)
        setTotal(res.total)
      }
    } catch (err) {
      if (seq === reqSeq) setError(formatApiError(err))
    } finally {
      if (seq === reqSeq) setLoading(false)
    }
  }, [actionFilter, targetTypeFilter, offset, reqSeq])

  useEffect(() => {
    fetchAuditLog()
  }, [fetchAuditLog])

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
          value={actionFilter}
          onChange={(e) => {
            setActionFilter(e.target.value)
            setOffset(0)
          }}
          className="settings-form__input"
          aria-label="Filter by action"
        >
          <option value="">All actions</option>
          {Object.entries(ACTION_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <select
          value={targetTypeFilter}
          onChange={(e) => {
            setTargetTypeFilter(e.target.value)
            setOffset(0)
          }}
          className="settings-form__input"
          aria-label="Filter by target type"
        >
          <option value="">All targets</option>
          <option value="container">Containers</option>
          <option value="user">Users</option>
        </select>
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
          <div className="audit-log-page__table-wrap">
            {entries.map((entry) => (
              <div key={entry.id} className="audit-log-page__row">
                <span className="audit-log-page__action">{actionLabel(entry.action)}</span>
                <span className="audit-log-page__target">
                  {entry.target_type}: {entry.target_id.slice(0, 8)}
                </span>
                <span className="audit-log-page__time">
                  {new Date(entry.created_at).toLocaleString()}
                </span>
              </div>
            ))}
            {entries.length === 0 && (
              <div className="audit-log-page__empty">No audit entries found</div>
            )}
          </div>
          <div className="audit-log-page__pagination">
            {offset > 0 && (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => setOffset(offset - LIMIT)}
              >
                Previous
              </button>
            )}
            {offset + LIMIT < total && (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => setOffset(offset + LIMIT)}
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
