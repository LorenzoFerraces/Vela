import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { exportLogs, formatApiError, getLogs } from '../api/client'
import type { LogEntry, LogQueryParams } from '../api/client'

const LEVEL_STYLES: Record<string, CSSProperties> = {
  info: { backgroundColor: 'rgba(107, 114, 128, 0.12)', color: '#9aa5b4' },
  warn: { backgroundColor: 'rgba(251, 191, 36, 0.12)', color: '#fbbf24' },
  error: { backgroundColor: 'rgba(239, 68, 68, 0.12)', color: '#ef4444' },
  debug: { backgroundColor: 'rgba(122, 134, 153, 0.12)', color: '#7a8699' },
}

const LIMIT = 100

export default function LogsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const fetchRequestRef = useRef(0)

  const search = searchParams.get('q') ?? ''
  const levelFilter = searchParams.get('level') ?? ''
  const containerFilter = searchParams.get('container_id') ?? ''
  const offsetParam = Number.parseInt(searchParams.get('offset') ?? '0', 10)
  const offset = Number.isNaN(offsetParam) ? 0 : offsetParam

  const hasContainer = containerFilter.trim().length > 0

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
          name="q"
          autoComplete="off"
          aria-label="Search logs"
          placeholder="Search logs…"
          value={search}
          onChange={(e) => {
            setFilterParam('q', e.target.value)
            setEntries([])
            setLoading(true)
          }}
        />
        <select
          name="level"
          value={levelFilter}
          onChange={(e) => {
            setFilterParam('level', e.target.value)
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
          name="container_id"
          autoComplete="off"
          placeholder="Container ID…"
          value={containerFilter}
          onChange={(e) => {
            setFilterParam('container_id', e.target.value)
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
              return (
                <div key={`${entry.timestamp}-${index}`} className="logs-page__row">
                  <span
                    className="logs-page__level"
                    style={LEVEL_STYLES[entry.level] ?? LEVEL_STYLES.info}
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
                  setOffsetParam(offset - LIMIT)
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
                  setOffsetParam(offset + LIMIT)
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
