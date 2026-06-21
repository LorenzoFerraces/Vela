import { useCallback, useEffect, useState } from 'react'
import {
  formatApiError,
  getDeploymentDiff,
  listDeployments,
  type DeploymentDiffResponse,
  type DeploymentRecord,
} from '../../api/client'
import { deploySourceImageLabel } from './deploySourceDisplay'

function formatWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return iso
  }
  return date.toLocaleString()
}

function formatSourceCell(row: DeploymentRecord): string {
  const label = deploySourceImageLabel(row)
  if (row.source_kind === 'git' && row.git_branch) {
    return `${label} @ ${row.git_branch}`
  }
  if (row.source_kind === 'dockerfile_template') {
    return `Dockerfile: ${label}`
  }
  return label
}

function formatCompareOptionLabel(row: DeploymentRecord): string {
  return `${formatWhen(row.created_at)} — ${deploySourceImageLabel(row)}`
}

function maskEnvValue(value: string): string {
  if (value.length <= 4) {
    return '****'
  }
  return `****${value.slice(-4)}`
}

function EnvDiffValue({
  itemKey,
  value,
}: {
  itemKey: string
  value: string
}) {
  const [revealed, setRevealed] = useState(false)
  const displayValue = revealed ? value : maskEnvValue(value)

  return (
    <span className="deployment-history__env-value">
      {displayValue}
      <button
        type="button"
        className="btn btn--ghost btn--sm deployment-history__env-reveal"
        onClick={() => setRevealed((previous) => !previous)}
        aria-pressed={revealed}
        aria-label={revealed ? `Hide value for ${itemKey}` : `Reveal value for ${itemKey}`}
      >
        {revealed ? 'Hide' : 'Reveal'}
      </button>
    </span>
  )
}

function EnvDiffLine({
  lineKey,
  prefix,
  envKey,
  value,
}: {
  lineKey: string
  prefix: string
  envKey: string
  value: string
}) {
  return (
    <li key={lineKey}>
      {prefix} {envKey}=<EnvDiffValue itemKey={envKey} value={value} />
    </li>
  )
}

function EnvChangeLine({
  lineKey,
  envKey,
  before,
  after,
}: {
  lineKey: string
  envKey: string
  before: string
  after: string
}) {
  return (
    <li key={lineKey}>
      ~ {envKey}:{' '}
      <EnvDiffValue itemKey={`${envKey}-before`} value={before} />
      {' → '}
      <EnvDiffValue itemKey={`${envKey}-after`} value={after} />
    </li>
  )
}

export function DeploymentHistorySection({
  refreshSignal = 0,
}: {
  refreshSignal?: number
}) {
  const [expanded, setExpanded] = useState(false)
  const [rows, setRows] = useState<DeploymentRecord[]>([])
  const [loading, setLoading] = useState(false)
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
    if (!expanded) {
      return
    }
    void reload()
  }, [reload, refreshSignal, expanded])

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
      <button
        type="button"
        className="deployment-history__toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((open) => !open)}
      >
        <span className="deployment-history__title">Deploy history</span>
        <span className="deployment-history__chevron" aria-hidden="true">
          ›
        </span>
      </button>

      {expanded ? (
      <>
      <div aria-live="polite" className="deployment-history__body">
        {loading && rows.length === 0 ? (
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
          <div className="containers-table-wrap workloads-table-wrap">
            <table className="containers-table workloads-table deployment-history__table">
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
                    <td className="deployment-history__when">{formatWhen(row.created_at)}</td>
                    <td className="deployment-history__author">{row.author_email}</td>
                    <td>
                      <span className="containers-status">{formatSourceCell(row)}</span>
                    </td>
                    <td
                      className="containers-table__mono"
                      title={
                        row.source_kind === 'dockerfile_template' ||
                        row.source_kind === 'git'
                          ? row.image_tag
                          : undefined
                      }
                    >
                      {deploySourceImageLabel(row)}
                    </td>
                    <td>{row.container_name ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      {rows.length >= 2 ? (
        <div className="deployment-history__compare">
          <h3 className="deployment-history__compare-title">Compare versions</h3>
          <div className="deployment-history__compare-controls">
            <label className="deployment-history__compare-field">
              <span className="containers-form__label">Older</span>
              <select
                className="containers-form__input"
                value={leftId}
                onChange={(event) => setLeftId(event.target.value)}
              >
                <option value="">Select…</option>
                {rows.map((row) => (
                  <option key={row.id} value={row.id}>
                    {formatCompareOptionLabel(row)}
                  </option>
                ))}
              </select>
            </label>
            <label className="deployment-history__compare-field">
              <span className="containers-form__label">Newer</span>
              <select
                className="containers-form__input"
                value={rightId}
                onChange={(event) => setRightId(event.target.value)}
              >
                <option value="">Select…</option>
                {rows.map((row) => (
                  <option key={row.id} value={row.id}>
                    {formatCompareOptionLabel(row)}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={!leftId || !rightId || leftId === rightId || diffLoading}
              onClick={() => void onCompare()}
            >
              {diffLoading ? 'Comparing…' : 'Compare'}
            </button>
          </div>

          {diff ? (
            <div className="deployment-history__diff">
              <h4 className="deployment-history__diff-heading">Environment changes</h4>
              {Object.keys(diff.env.added).length === 0 &&
              Object.keys(diff.env.removed).length === 0 &&
              Object.keys(diff.env.changed).length === 0 ? (
                <p className="containers-muted">No env changes.</p>
              ) : (
                <ul className="deployment-history__env-diff">
                  {Object.entries(diff.env.added).map(([key, value]) => (
                    <EnvDiffLine
                      key={`add-${key}`}
                      lineKey={`add-${key}`}
                      prefix="+"
                      envKey={key}
                      value={value}
                    />
                  ))}
                  {Object.entries(diff.env.removed).map(([key, value]) => (
                    <EnvDiffLine
                      key={`remove-${key}`}
                      lineKey={`remove-${key}`}
                      prefix="-"
                      envKey={key}
                      value={value}
                    />
                  ))}
                  {Object.entries(diff.env.changed).map(([key, change]) => (
                    <EnvChangeLine
                      key={`change-${key}`}
                      lineKey={`change-${key}`}
                      envKey={key}
                      before={change.before}
                      after={change.after}
                    />
                  ))}
                </ul>
              )}
              <h4 className="deployment-history__diff-heading">Dockerfile diff</h4>
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
      </>
      ) : null}
    </section>
  )
}
