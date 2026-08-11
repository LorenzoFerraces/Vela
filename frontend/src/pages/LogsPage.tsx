import { useCallback, useEffect, useState } from 'react'
import { exportLogs, getLogs } from '../api/client'
import type { LogEntry } from '../api/client'

const LEVEL_COLORS: Record<string, { bg: string; text: string }> = {
  info: { bg: '#6b728020', text: '#6b7280' },
  warn: { bg: '#f59e0b20', text: '#f59e0b' },
  error: { bg: '#ef444420', text: '#ef4444' },
  debug: { bg: '#9ca3af20', text: '#9ca3af' },
}

const LIMIT = 100

export default function LogsPage() {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [levelFilter, setLevelFilter] = useState('')
  const [containerFilter, setContainerFilter] = useState('')
  const [offset, setOffset] = useState(0)

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = { limit: LIMIT, offset }
      if (search) params.q = search
      if (levelFilter) params.level = levelFilter
      if (containerFilter) params.container_id = containerFilter
      const res = await getLogs(params as any)
      setEntries(res.entries)
      setTotal(res.total)
    } catch (error) {
      console.error('Failed to fetch logs', error)
    } finally {
      setLoading(false)
    }
  }, [search, levelFilter, containerFilter, offset])

  useEffect(() => {
    fetchLogs()
  }, [fetchLogs])

  const handleExport = async () => {
    const params: Record<string, string> = {}
    if (levelFilter) params.level = levelFilter
    if (containerFilter) params.container_id = containerFilter
    await exportLogs(params as any)
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Logs</h1>
        <button
          onClick={handleExport}
          className="px-3 py-1.5 text-sm bg-gray-800 text-white rounded hover:bg-gray-700"
        >
          Export CSV
        </button>
      </div>

      <div className="flex gap-3 mb-4">
        <input
          type="text"
          placeholder="Search logs..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setOffset(0)
          }}
          className="flex-1 px-3 py-2 border rounded bg-white text-sm"
        />
        <select
          value={levelFilter}
          onChange={(e) => {
            setLevelFilter(e.target.value)
            setOffset(0)
          }}
          className="px-3 py-2 border rounded bg-white text-sm"
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
          }}
          className="px-3 py-2 border rounded bg-white text-sm w-48"
        />
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              className="h-8 bg-gray-200 animate-pulse rounded"
            />
          ))}
        </div>
      ) : (
        <>
          <div className="text-sm text-gray-500 mb-2">
            Showing {entries.length} of {total} entries
          </div>
          <div className="border rounded bg-white">
            {entries.map((entry, index) => {
              const color =
                LEVEL_COLORS[entry.level] ?? LEVEL_COLORS.info
              return (
                <div
                  key={index}
                  className="flex items-start gap-3 px-4 py-2 border-b last:border-b-0 font-mono text-sm"
                >
                  <span
                    className="w-12 shrink-0 text-xs py-0.5 px-1.5 rounded text-center"
                    style={{
                      backgroundColor: color.bg,
                      color: color.text,
                    }}
                  >
                    {entry.level}
                  </span>
                  <span className="text-gray-400 shrink-0 text-xs w-28">
                    {new Date(entry.timestamp).toLocaleString()}
                  </span>
                  <span className="text-gray-400 shrink-0 text-xs w-24 truncate">
                    {entry.container_name || entry.container_id}
                  </span>
                  <span className="flex-1 break-all">{entry.message}</span>
                </div>
              )
            })}
            {entries.length === 0 && (
              <div className="px-4 py-8 text-center text-gray-400">
                No logs found
              </div>
            )}
          </div>
          <div className="flex gap-2 mt-3">
            {offset > 0 && (
              <button
                onClick={() => setOffset(offset - LIMIT)}
                className="px-3 py-1.5 text-sm border rounded hover:bg-gray-50"
              >
                Previous
              </button>
            )}
            {offset + LIMIT < total && (
              <button
                onClick={() => setOffset(offset + LIMIT)}
                className="px-3 py-1.5 text-sm border rounded hover:bg-gray-50"
              >
                Next
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
