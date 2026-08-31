import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowClockwise,
  DotsThree,
  IdentificationBadge,
  Play,
  RocketLaunch,
  Stop,
  TerminalWindow,
  Trash,
  UserCircle,
} from '@phosphor-icons/react'
import { formatApiError, getAuditLog } from '../api/client'
import type {
  AuditLogEntry,
  AuditLogQueryParams,
} from '../api/client'
import './audit/audit.css'

const LIMIT = 50

type ActionMeta = {
  label: string
  sentence: string
  Icon: typeof Play
}

const ACTION_META: Record<string, ActionMeta> = {
  'container.deploy': {
    label: 'Deploy',
    sentence: 'Deployed container',
    Icon: RocketLaunch,
  },
  'container.start': {
    label: 'Start',
    sentence: 'Started container',
    Icon: Play,
  },
  'container.stop': {
    label: 'Stop',
    sentence: 'Stopped container',
    Icon: Stop,
  },
  'container.restart': {
    label: 'Restart',
    sentence: 'Restarted container',
    Icon: ArrowClockwise,
  },
  'container.remove': {
    label: 'Remove',
    sentence: 'Removed container',
    Icon: Trash,
  },
  'container.exec': {
    label: 'Exec',
    sentence: 'Ran command in container',
    Icon: TerminalWindow,
  },
  'user.profile_update': {
    label: 'Profile update',
    sentence: 'Updated profile',
    Icon: IdentificationBadge,
  },
  'user.avatar_upload': {
    label: 'Avatar upload',
    sentence: 'Uploaded avatar',
    Icon: UserCircle,
  },
  'user.avatar_removed': {
    label: 'Avatar removed',
    sentence: 'Removed avatar',
    Icon: UserCircle,
  },
}

const FALLBACK_META: ActionMeta = {
  label: '',
  sentence: 'Performed action',
  Icon: DotsThree,
}

type DayGroup = {
  key: string
  label: string
  entries: AuditLogEntry[]
}

function dayLabel(date: Date, now: Date): string {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const diffDays = Math.round((today.getTime() - day.getTime()) / 86_400_000)
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  return date.toLocaleDateString([], {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function groupByDay(entries: AuditLogEntry[]): DayGroup[] {
  const now = new Date()
  const groups: DayGroup[] = []
  for (const entry of entries) {
    const date = new Date(entry.created_at)
    const key = date.toDateString()
    const last = groups[groups.length - 1]
    if (last && last.key === key) {
      last.entries.push(entry)
    } else {
      groups.push({ key, label: dayLabel(date, now), entries: [entry] })
    }
  }
  return groups
}

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [searchParams, setSearchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const requestSeq = useRef(0)

  const actionFilter = searchParams.get('action') ?? ''
  const targetTypeFilter = searchParams.get('target') ?? ''
  const fromRaw = searchParams.get('from') ?? ''
  const toRaw = searchParams.get('to') ?? ''
  const offsetParam = Number.parseInt(searchParams.get('offset') ?? '0', 10)
  const offset = Number.isNaN(offsetParam) ? 0 : offsetParam

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

  const filterParams = useMemo<AuditLogQueryParams>(() => {
    const params: AuditLogQueryParams = { limit: LIMIT, offset }
    if (actionFilter) params.action = actionFilter
    if (targetTypeFilter) params.target_type = targetTypeFilter
    if (fromRaw) params.from_date = new Date(`${fromRaw}T00:00:00`).toISOString()
    if (toRaw) params.to_date = new Date(`${toRaw}T23:59:59`).toISOString()
    return params
  }, [actionFilter, targetTypeFilter, fromRaw, toRaw, offset])

  const load = useCallback(async (params: AuditLogQueryParams) => {
    const seq = ++requestSeq.current
    setLoading(true)
    setError(null)
    try {
      const data = await getAuditLog(params)
      if (seq === requestSeq.current) {
        setEntries(data.entries)
        setTotal(data.total)
      }
    } catch (err) {
      if (seq === requestSeq.current) setError(formatApiError(err))
    } finally {
      if (seq === requestSeq.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(filterParams)
  }, [load, filterParams])

  const groups = useMemo(() => groupByDay(entries), [entries])

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
          aria-label="Filter by action"
          className="settings-form__input"
          value={actionFilter}
          onChange={(e) => setFilterParam('action', e.target.value)}
        >
          <option value="">All actions</option>
          {Object.entries(ACTION_META).map(([value, meta]) => (
            <option key={value} value={value}>
              {meta.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by target type"
          className="settings-form__input"
          value={targetTypeFilter}
          onChange={(e) => setFilterParam('target', e.target.value)}
        >
          <option value="">All targets</option>
          <option value="container">Containers</option>
          <option value="user">Users</option>
        </select>
        <input
          type="date"
          aria-label="From date"
          className="settings-form__input"
          value={fromRaw}
          onChange={(e) => setFilterParam('from', e.target.value)}
        />
        <input
          type="date"
          aria-label="To date"
          className="settings-form__input"
          value={toRaw}
          onChange={(e) => setFilterParam('to', e.target.value)}
        />
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
          <div className="audit-log-page__timeline">
            {groups.map((group) => (
              <div key={group.key} className="audit-log-page__day">
                <h2 className="audit-log-page__day-label">{group.label}</h2>
                {group.entries.map((entry) => {
                  const meta = ACTION_META[entry.action] ?? {
                    ...FALLBACK_META,
                    label: entry.action,
                  }
                  const Icon = meta.Icon
                  const isSelf = entry.target_type === 'user'
                  return (
                    <div key={entry.id} className="audit-log-page__row">
                      <Icon
                        size={16}
                        className="audit-log-page__icon"
                        aria-hidden="true"
                      />
                      <span className="audit-log-page__sentence">
                        {meta.sentence}
                        {!isSelf ? (
                          <>
                            {' '}
                            <code className="audit-log-page__target-id">
                              {entry.target_id.slice(0, 8)}
                            </code>
                          </>
                        ) : null}
                      </span>
                      <span className="audit-log-page__time">
                        {new Date(entry.created_at).toLocaleString([], {
                          hour12: false,
                        })}
                      </span>
                      {entry.details ? (
                        <details className="audit-log-page__details">
                          <summary>Details</summary>
                          <pre>{JSON.stringify(entry.details, null, 2)}</pre>
                        </details>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            ))}
            {entries.length === 0 && (
              <div className="audit-log-page__empty">
                No audit entries found
              </div>
            )}
          </div>
          <div className="audit-log-page__pagination">
            {offset > 0 && (
              <button
                type="button"
                onClick={() => setOffsetParam(offset - LIMIT)}
                className="btn btn--ghost btn--sm"
              >
                Previous
              </button>
            )}
            {offset + LIMIT < total && (
              <button
                type="button"
                onClick={() => setOffsetParam(offset + LIMIT)}
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
