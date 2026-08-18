import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { exportLogs, formatApiError, getLogs } from '../api/client'
import type { LogEntry, LogQueryParams } from '../api/client'

const LEVEL_STYLES: Record<string, { bg: string; text: string }> = {
  info: { bg: 'rgba(107, 114, 128, 0.12)', text: '#9aa5b4' },
  warn: { bg: 'rgba(232, 184, 74, 0.12)', text: '#e8b84a' },
  error: { bg: 'rgba(224, 112, 110, 0.12)', text: '#e0706e' },
  debug: { bg: 'rgba(122, 134, 153, 0.12)', text: '#7a8699' },
}

const LIMIT = 100

export default function LogsPage() {
  const [searchParams] = useSearchParams()
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [levelFilter, setLevelFilter] = useState('')
  const [containerFilter, setContainerFilter] = useState(
    () => searchParams.get('container_id') ?? ''
  )
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const fetchRequestRef = useRef(0)

  const hasContainer = containerFilter.trim().length > 0

  const fetchLogs = useCallback(async () => {
    const requestId = fetchRequestRef.current + 1
    fetchRequestRef.current = requestId
    const params: LogQueryParams = {
      container_id: containerFilter.trim(),
      limit: LIMIT,
      offset,
    }
    if (search) params.q = search
    if (levelFilter) params.level = levelFilter
    try {
      const res = await getLogs(params)
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
  }, [search, levelFilter, containerFilter, offset])

  useEffect(() => {
    if (!hasContainer) return
    fetchLogs()
  }, [hasContainer, fetchLogs])

  const handleExport = async () => {
    if (!hasContainer) return
    const params: LogQueryParams = { container_id: containerFilter.trim() }
    if (search) params.q = search
    if (levelFilter) params.level = levelFilter
    try {
      await exportLogs(params)
    } catch (err) {
      setError(formatApiError(err))
    }
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
        <input
          type="text"
          placeholder="Search logs..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setOffset(0)
            setEntries([])
            setLoading(true)
          }}
        />
        <select
          value={levelFilter}
          onChange={(e) => {
            setLevelFilter(e.target.value)
            setOffset(0)
            setEntries([])
            setLoading(true)
          }}
          className="settings-form__input"
          aria-label="Filter by level"
        >
          <option value="">All levels</option>
          <option value="info">Info</option>
          <option value="warn">Warn</option>
          <option value="error">Error</option>
          <option value="debug">Debug</option>
        </select>
        <input
          type="text"
          placeholder="Container ID..."
          value={containerFilter}
          onChange={(e) => {
            setContainerFilter(e.target.value)
            setOffset(0)
            setEntries([])
            setLoading(true)
          }}
          className="settings-form__input"
          aria-label="Filter by container"
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
          <div className="logs-page__table-wrap">
            {entries.map((entry, index) => {
              const style = LEVEL_STYLES[entry.level] ?? LEVEL_STYLES.info
              return (
                <div key={index} className="logs-page__row">
                  <span
                    className="logs-page__level"
                    style={{
                      backgroundColor: style.bg,
                      color: style.text,
                    }}
                  >
                    {entry.level}
                  </span>
                  <span className="logs-page__timestamp">
                    {new Date(entry.timestamp).toLocaleString()}
                  </span>
                  <span className="logs-page__container">
                    {entry.container_name || entry.container_id}
                  </span>
                  <span className="logs-page__message">{entry.message}</span>
                </div>
              )
            })}
            {entries.length === 0 && (
              <div className="logs-page__empty">No logs found</div>
            )}
          </div>
          <div className="logs-page__pagination">
            {offset > 0 && (
              <button
                type="button"
                onClick={() => {
                  setOffset(offset - LIMIT)
                  setEntries([])
                  setLoading(true)
                }}
                className="btn btn--ghost btn--sm"
              >
                Previous
              </button>
            )}
            {offset + LIMIT < total && (
              <button
                type="button"
                onClick={() => {
                  setOffset(offset + LIMIT)
                  setEntries([])
                  setLoading(true)
                }}
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
