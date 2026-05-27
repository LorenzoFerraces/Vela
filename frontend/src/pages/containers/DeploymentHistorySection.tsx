import { useCallback, useEffect, useState } from 'react'
import {
  formatApiError,
  getDeploymentDiff,
  listDeployments,
  type DeploymentDiffResponse,
  type DeploymentRecord,
} from '../../api/client'

function formatWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return iso
  }
  return date.toLocaleString()
}

export function DeploymentHistorySection() {
  const [rows, setRows] = useState<DeploymentRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [leftId, setLeftId] = useState<string>('')
  const [rightId, setRightId] = useState<string>('')
  const [diff, setDiff] = useState<DeploymentDiffResponse | null>(null)
  const [diffLoading, setDiffLoading] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listDeployments({ limit: 30 })
      setRows(data)
    } catch (loadError) {
      setError(formatApiError(loadError))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  async function onCompare() {
    if (!leftId || !rightId || leftId === rightId) {
      return
    }
    setDiffLoading(true)
    setError(null)
    try {
      const result = await getDeploymentDiff(leftId, rightId)
      setDiff(result)
    } catch (compareError) {
      setError(formatApiError(compareError))
      setDiff(null)
    } finally {
      setDiffLoading(false)
    }
  }

  return (
    <section className="deployment-history">
      <div className="deployment-history__header">
        <h2 className="dashboard-page__subtitle">Deploy history</h2>
        <button
          type="button"
          className="btn btn--ghost btn--compact"
          onClick={() => void reload()}
          disabled={loading}
        >
          Refresh
        </button>
      </div>

      {loading ? (
        <p className="containers-muted">Loading deploy history…</p>
      ) : null}
      {error ? (
        <p className="containers-form-message containers-form-message--err" role="alert">
          {error}
        </p>
      ) : null}

      {!loading && rows.length === 0 ? (
        <p className="containers-muted">No deployments recorded yet.</p>
      ) : null}

      {rows.length > 0 ? (
        <div className="deployment-history__table-wrap">
          <table className="workloads-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Author</th>
                <th>Source</th>
                <th>Image</th>
                <th>Name</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{formatWhen(row.created_at)}</td>
                  <td>{row.author_email}</td>
                  <td>
                    {row.source_kind}
                    {row.git_branch ? ` @ ${row.git_branch}` : ''}
                  </td>
                  <td>{row.image_tag}</td>
                  <td>{row.container_name ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {rows.length >= 2 ? (
        <div className="deployment-history__compare">
          <h3 className="deployment-history__compare-title">Compare versions</h3>
          <div className="deployment-history__compare-controls">
            <label>
              <span className="containers-form__label">Older</span>
              <select
                className="containers-form__input"
                value={leftId}
                onChange={(event) => setLeftId(event.target.value)}
              >
                <option value="">Select…</option>
                {rows.map((row) => (
                  <option key={row.id} value={row.id}>
                    {formatWhen(row.created_at)} — {row.image_tag}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="containers-form__label">Newer</span>
              <select
                className="containers-form__input"
                value={rightId}
                onChange={(event) => setRightId(event.target.value)}
              >
                <option value="">Select…</option>
                {rows.map((row) => (
                  <option key={row.id} value={row.id}>
                    {formatWhen(row.created_at)} — {row.image_tag}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={!leftId || !rightId || leftId === rightId || diffLoading}
              onClick={() => void onCompare()}
            >
              {diffLoading ? 'Comparing…' : 'Compare'}
            </button>
          </div>

          {diff ? (
            <div className="deployment-history__diff">
              <h4>Environment changes</h4>
              {Object.keys(diff.env.added).length === 0 &&
              Object.keys(diff.env.removed).length === 0 &&
              Object.keys(diff.env.changed).length === 0 ? (
                <p className="containers-muted">No env changes.</p>
              ) : (
                <ul className="deployment-history__env-diff">
                  {Object.entries(diff.env.added).map(([key, value]) => (
                    <li key={`add-${key}`}>+ {key}={value}</li>
                  ))}
                  {Object.entries(diff.env.removed).map(([key, value]) => (
                    <li key={`remove-${key}`}>- {key}={value}</li>
                  ))}
                  {Object.entries(diff.env.changed).map(([key, change]) => (
                    <li key={`change-${key}`}>
                      ~ {key}: {change.before} → {change.after}
                    </li>
                  ))}
                </ul>
              )}
              <h4>Dockerfile diff</h4>
              {diff.dockerfile_diff.length === 0 ? (
                <p className="containers-muted">No Dockerfile diff.</p>
              ) : (
                <pre className="deployment-history__dockerfile-diff">
                  {diff.dockerfile_diff.join('\n')}
                </pre>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
