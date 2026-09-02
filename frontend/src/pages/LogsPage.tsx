import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  exportLogs,
  formatApiError,
  getLogs,
  listContainers,
} from '../api/client'
import type { ContainerInfo, LogEntry, LogQueryParams } from '../api/client'
import { ContainerLogPanel } from '../components/workloads/ContainerLogPanel'
import './logs/logs.css'

const LIMIT = 100
const SEARCH_DEBOUNCE_MS = 320

export default function LogsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [containers, setContainers] = useState<ContainerInfo[]>([])
  const fetchRequestRef = useRef(0)

  const search = searchParams.get('q') ?? ''
  const [debouncedSearch, setDebouncedSearch] = useState(
    () => searchParams.get('q') ?? '',
  )
  const levelFilter = searchParams.get('level') ?? ''
  const containerFilter = searchParams.get('container_id') ?? ''
  const startRaw = searchParams.get('start') ?? ''
  const endRaw = searchParams.get('end') ?? ''
  const offsetParam = Number.parseInt(searchParams.get('offset') ?? '0', 10)
  const offset = Number.isNaN(offsetParam) ? 0 : offsetParam

  const hasContainer = containerFilter.trim().length > 0

  useEffect(() => {
    let active = true
    listContainers()
      .then((data) => {
        if (active) setContainers(data)
      })
      .catch(() => {
        // ponytail: picker stays empty on failure; URL-param container still works
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedSearch(search),
      SEARCH_DEBOUNCE_MS,
    )
    return () => window.clearTimeout(timer)
  }, [search])

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

  const buildParams = useCallback(
    (includeOffset: boolean): LogQueryParams => {
      const params: LogQueryParams = {
        container_id: containerFilter.trim(),
        limit: LIMIT,
      }
      if (includeOffset) params.offset = offset
      if (debouncedSearch) params.q = debouncedSearch
      if (levelFilter) params.level = levelFilter
      const startDate = startRaw ? new Date(startRaw) : null
      if (startDate && !Number.isNaN(startDate.getTime())) {
        params.start_time = startDate.toISOString()
      }
      const endDate = endRaw ? new Date(endRaw) : null
      if (endDate && !Number.isNaN(endDate.getTime())) {
        params.end_time = endDate.toISOString()
      }
      return params
    },
    [debouncedSearch, levelFilter, containerFilter, startRaw, endRaw, offset],
  )

  const fetchLogs = useCallback(async () => {
    const requestId = fetchRequestRef.current + 1
    fetchRequestRef.current = requestId
    try {
      const res = await getLogs(buildParams(true))
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
  }, [buildParams])

  useEffect(() => {
    if (!hasContainer) return
    fetchLogs()
  }, [hasContainer, fetchLogs])

  const handleExport = async () => {
    if (!hasContainer) return
    try {
      await exportLogs(buildParams(false))
    } catch (err) {
      setError(formatApiError(err))
    }
  }

  const knownContainer = containers.some(
    (container) => container.id === containerFilter,
  )
  const selectedContainer =
    containers.find((container) => container.id === containerFilter) ?? null

  function onFilterChange(name: string, value: string) {
    setFilterParam(name, value)
    setEntries([])
    setLoading(true)
  }

  function onOffsetChange(value: number) {
    setOffsetParam(value)
    setEntries([])
    setLoading(true)
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
        <div className="settings-form__field">
          <label className="settings-form__label" htmlFor="logs-filter-container">
            Container
          </label>
          <select
            id="logs-filter-container"
            className="settings-form__input logs-page__container-select"
            value={containerFilter}
            onChange={(e) => onFilterChange('container_id', e.target.value)}
          >
            <option value="">Select a container…</option>
            {containerFilter && !knownContainer ? (
              <option value={containerFilter}>
                {containerFilter.slice(0, 8)}
              </option>
            ) : null}
            {containers.map((container) => (
              <option key={container.id} value={container.id}>
                {container.name || container.id.slice(0, 8)} (
                {container.status})
              </option>
            ))}
          </select>
        </div>
        <div className="settings-form__field">
          <label className="settings-form__label" htmlFor="logs-filter-level">
            Level
          </label>
          <select
            id="logs-filter-level"
            className="settings-form__input"
            value={levelFilter}
            onChange={(e) => onFilterChange('level', e.target.value)}
          >
            <option value="">All levels</option>
            <option value="info">Info</option>
            <option value="warn">Warn</option>
            <option value="error">Error</option>
            <option value="debug">Debug</option>
          </select>
        </div>
        <div className="settings-form__field">
          <label className="settings-form__label" htmlFor="logs-filter-from">
            From
          </label>
          <input
            id="logs-filter-from"
            type="datetime-local"
            className="settings-form__input"
            value={startRaw}
            onChange={(e) => onFilterChange('start', e.target.value)}
          />
        </div>
        <div className="settings-form__field">
          <label className="settings-form__label" htmlFor="logs-filter-to">
            To
          </label>
          <input
            id="logs-filter-to"
            type="datetime-local"
            className="settings-form__input"
            value={endRaw}
            onChange={(e) => onFilterChange('end', e.target.value)}
          />
        </div>
        <div className="settings-form__field logs-page__search-field">
          <label className="settings-form__label" htmlFor="logs-filter-search">
            Search
          </label>
          <input
            id="logs-filter-search"
            type="text"
            autoComplete="off"
            placeholder="Search logs…"
            className="logs-page__search"
            value={search}
            onChange={(e) => onFilterChange('q', e.target.value)}
          />
        </div>
      </div>

      {hasContainer && selectedContainer?.status === 'running' ? (
        <div className="logs-page__live">
          <ContainerLogPanel
            containerId={containerFilter}
            isActive
            workloadStatus={selectedContainer.status}
          />
        </div>
      ) : null}

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
          <div
            className="logs-page__terminal"
            role="log"
            aria-label="Log entries"
          >
            {entries.map((entry, index) => (
              <div
                key={`${entry.timestamp}-${index}`}
                className="logs-page__line"
              >
                <span className="logs-page__line-time">
                  {new Date(entry.timestamp).toLocaleString([], {
                    hour12: false,
                  })}
                </span>
                <span
                  className={`logs-page__line-level logs-page__line-level--${entry.level}`}
                >
                  {entry.level}
                </span>
                <span className="logs-page__line-source">
                  {entry.source}
                </span>
                <span className="logs-page__line-message">
                  {entry.message}
                </span>
              </div>
            ))}
            {entries.length === 0 && (
              <div className="logs-page__empty">No logs found</div>
            )}
          </div>
          <div className="logs-page__pagination">
            {offset > 0 && (
              <button
                type="button"
                onClick={() => onOffsetChange(offset - LIMIT)}
                className="btn btn--ghost btn--sm"
              >
                Previous
              </button>
            )}
            {offset + LIMIT < total && (
              <button
                type="button"
                onClick={() => onOffsetChange(offset + LIMIT)}
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
