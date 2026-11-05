import { useEffect, useState } from 'react'
import { formatApiError, getGlobalAudit } from '../../api/client'
import type { AuditLogEntry } from '../../api/client'
import { Skeleton } from '../../components/Skeleton'

const LIMIT = 50

type AuditPanelProps = {
  active: boolean
}

function displayDate(value: string): string {
  return new Date(value).toLocaleString([], { hour12: false })
}

export default function AuditPanel({ active }: AuditPanelProps) {
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!active) return
    let current = true
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const response = await getGlobalAudit({ limit: LIMIT, offset })
        if (!current) return
        setEntries(response.entries)
        setTotal(response.total)
      } catch (loadError) {
        if (current) setError(formatApiError(loadError))
      } finally {
        if (current) setLoading(false)
      }
    }
    void load()
    return () => {
      current = false
    }
  }, [active, offset])

  return (
    <section className="admin-audit" aria-labelledby="admin-audit-heading">
      <header className="admin-audit__header">
        <div>
          <h2 id="admin-audit-heading">Global audit</h2>
          <p className="admin-audit__lead">Actions recorded across the workspace.</p>
        </div>
      </header>

      {error ? <p className="settings-banner settings-banner--err" role="alert">{error}</p> : null}

      {loading ? (
        <div className="admin-audit__table-wrap" aria-busy="true" aria-label="Loading audit entries">
          <table className="admin-audit__table">
            <thead><tr><th>Action</th><th>Target</th><th>Actor</th><th>When</th><th>Details</th></tr></thead>
            <tbody>
              {Array.from({ length: 5 }).map((_, index) => (
                <tr key={index}><td colSpan={5}><Skeleton className="skeleton--team-row" /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : error && entries.length === 0 ? null : entries.length === 0 ? (
        <div className="admin-audit__empty">No audit entries found</div>
      ) : (
        <div className="admin-audit__table-wrap">
          <table className="admin-audit__table">
            <thead><tr><th>Action</th><th>Target</th><th>Actor</th><th>When</th><th>Details</th></tr></thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td>{entry.action}</td>
                  <td>{entry.target_type} / {entry.target_id.slice(0, 8)}</td>
                  <td>{entry.user_id.slice(0, 8)}</td>
                  <td>{displayDate(entry.created_at)}</td>
                  <td>
                    {entry.details ? (
                      <details className="admin-audit__details">
                        <summary>View</summary>
                        <pre>{JSON.stringify(entry.details, null, 2)}</pre>
                      </details>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && entries.length > 0 ? (
        <div className="admin-audit__pagination">
          <span>Showing {entries.length} of {total}</span>
          <div>
            {offset > 0 ? <button type="button" className="btn btn--ghost btn--sm" onClick={() => setOffset(Math.max(0, offset - LIMIT))}>Previous</button> : null}
            {offset + LIMIT < total ? <button type="button" className="btn btn--ghost btn--sm" onClick={() => setOffset(offset + LIMIT)}>Next</button> : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}
