import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ContainerInfo, ContainerStatus } from '../../api/client'
import {
  fetchContainerLogs,
  formatApiError,
  openContainerLogWebSocket,
} from '../../api/client'

const ERROR_LINE_PATTERN = /\b(error|exception|fatal|traceback)\b/i

type WorkloadsTableProps = {
  listLoading: boolean
  rows: ContainerInfo[]
  rowBusyId: string | null
  onStart: (containerId: string) => void
  onStop: (containerId: string) => void
  onRemove: (containerId: string) => void
  /** When true, show containers that need attention first (dashboard). */
  prioritizeProblemWorkloads?: boolean
}

function workloadConcernRank(row: ContainerInfo): number {
  if (row.status === 'stopped' || row.status === 'dead') {
    return 0
  }
  if (row.status === 'restarting') {
    return 1
  }
  const health = (row.health || '').toLowerCase()
  if (health && health !== 'none' && health !== 'healthy') {
    return 2
  }
  return 3
}

function sortRowsForDashboard(rows: ContainerInfo[]): ContainerInfo[] {
  return [...rows].sort((rowA, rowB) => {
    const rankA = workloadConcernRank(rowA)
    const rankB = workloadConcernRank(rowB)
    if (rankA !== rankB) {
      return rankA - rankB
    }
    return rowA.name.localeCompare(rowB.name)
  })
}

function ContainerLogPanel({
  containerId,
  isActive,
  workloadStatus,
}: {
  containerId: string
  isActive: boolean
  workloadStatus: ContainerStatus
}) {
  const isRunning = workloadStatus === 'running'
  const [logText, setLogText] = useState('')
  const [streamStatus, setStreamStatus] = useState<
    'connecting' | 'live' | 'ended' | 'err'
  >('connecting')
  const [errorText, setErrorText] = useState<string | null>(null)
  const [highlightErrors, setHighlightErrors] = useState(false)
  const decoderRef = useRef(new TextDecoder())

  const refreshSnapshot = useCallback(async () => {
    try {
      const snapshot = await fetchContainerLogs(containerId, { tail: 500 })
      setLogText(snapshot)
      setErrorText(null)
    } catch (error) {
      setErrorText(formatApiError(error))
    }
  }, [containerId])

  useEffect(() => {
    if (!isActive || isRunning) {
      return
    }
    void refreshSnapshot()
  }, [isActive, isRunning, containerId, refreshSnapshot])

  useEffect(() => {
    if (!isActive || !isRunning) {
      return
    }

    decoderRef.current = new TextDecoder()
    setLogText('')
    setStreamStatus('connecting')
    setErrorText(null)

    let websocket: WebSocket
    try {
      websocket = openContainerLogWebSocket(containerId, {
        tail: 400,
        follow: true,
      })
    } catch (error) {
      queueMicrotask(() => {
        setStreamStatus('err')
        setErrorText(formatApiError(error))
      })
      return
    }
    websocket.binaryType = 'arraybuffer'
    websocket.onopen = () => {
      queueMicrotask(() => {
        setStreamStatus('live')
      })
    }
    websocket.onmessage = (event) => {
      const payload = event.data
      const chunk =
        payload instanceof ArrayBuffer
          ? new Uint8Array(payload)
          : typeof payload === 'string'
            ? new TextEncoder().encode(payload)
            : new Uint8Array()
      if (chunk.length === 0) {
        return
      }
      const piece = decoderRef.current.decode(chunk, { stream: true })
      setLogText((previous) => previous + piece)
    }
    websocket.onerror = () => {
      queueMicrotask(() => {
        setErrorText('Log stream connection failed.')
        setStreamStatus('err')
      })
    }
    websocket.onclose = () => {
      queueMicrotask(() => {
        setStreamStatus((previous) => (previous === 'err' ? previous : 'ended'))
      })
    }
    return () => {
      websocket.onopen = null
      websocket.onmessage = null
      websocket.onerror = null
      websocket.onclose = null
      websocket.close()
    }
  }, [containerId, isActive, isRunning])

  const lines = useMemo(() => logText.split('\n'), [logText])

  return (
    <div className="workloads-log-panel">
      <div className="workloads-log-panel__toolbar">
        <span className="workloads-log-panel__status" role="status">
          {!isRunning
            ? 'Stream paused'
            : streamStatus === 'connecting'
              ? 'Connecting…'
              : streamStatus === 'live'
                ? 'Live'
                : streamStatus === 'ended'
                  ? 'Stream ended'
                  : 'Error'}
        </span>
        <label className="workloads-log-panel__toggle">
          <input
            type="checkbox"
            checked={highlightErrors}
            onChange={(event) => setHighlightErrors(event.target.checked)}
          />
          Highlight error lines
        </label>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => void refreshSnapshot()}
        >
          Refresh snapshot
        </button>
      </div>
      {errorText ? (
        <p className="workloads-log-panel__error" role="alert">
          {errorText}
        </p>
      ) : null}
      <pre
        className="workloads-log-panel__pre"
        tabIndex={0}
        aria-label="Container log output"
      >
        {lines.map((line, index) => {
          const key = `${index}-${line.slice(0, 24)}`
          if (highlightErrors && ERROR_LINE_PATTERN.test(line)) {
            return (
              <span key={key} className="workloads-log-panel__line workloads-log-panel__line--warn">
                {line}
                {'\n'}
              </span>
            )
          }
          return (
            <span key={key} className="workloads-log-panel__line">
              {line}
              {'\n'}
            </span>
          )
        })}
      </pre>
    </div>
  )
}

export function WorkloadsTable({
  listLoading,
  rows,
  rowBusyId,
  onStart,
  onStop,
  onRemove,
  prioritizeProblemWorkloads = false,
}: WorkloadsTableProps) {
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null)
  const [copiedRowId, setCopiedRowId] = useState<string | null>(null)
  const [copyFailedRowId, setCopyFailedRowId] = useState<string | null>(null)

  const displayRows = useMemo(
    () =>
      prioritizeProblemWorkloads ? sortRowsForDashboard(rows) : rows,
    [prioritizeProblemWorkloads, rows],
  )

  function toggleLogRow(containerId: string) {
    setExpandedRowId((current) =>
      current === containerId ? null : containerId,
    )
  }

  function copyAccessUrl(accessUrl: string, rowId: string) {
    void navigator.clipboard.writeText(accessUrl).then(
      () => {
        setCopiedRowId(rowId)
        setCopyFailedRowId(null)
        window.setTimeout(() => {
          setCopiedRowId(null)
        }, 2000)
      },
      () => {
        setCopyFailedRowId(rowId)
        window.setTimeout(() => {
          setCopyFailedRowId(null)
        }, 2500)
      },
    )
  }

  return (
    <div aria-live="polite" className="workloads-table-wrap-outer">
      {listLoading && rows.length === 0 ? (
        <p className="containers-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="containers-muted">No Vela-managed containers yet.</p>
      ) : (
        <div className="containers-table-wrap workloads-table-wrap">
          <table className="containers-table workloads-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Image</th>
                <th>Status</th>
                <th>Ports</th>
                <th>Access URL</th>
                <th>Logs</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {displayRows.map((containerRow) => {
                const isExpanded = expandedRowId === containerRow.id
                const accessUrl = containerRow.access_url?.trim() || ''
                return (
                  <Fragment key={containerRow.id}>
                    <tr>
                      <td>{containerRow.name}</td>
                      <td className="containers-table__mono">{containerRow.image}</td>
                      <td>
                        <span className="containers-status">{containerRow.status}</span>
                      </td>
                      <td className="containers-table__ports">
                        {containerRow.ports.length === 0
                          ? '—'
                          : containerRow.ports
                              .map(
                                (portMapping) =>
                                  `${portMapping.host_port}:${portMapping.container_port}/${portMapping.protocol}`,
                              )
                              .join(', ')}
                      </td>
                      <td className="workloads-table__url-cell">
                        {accessUrl ? (
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            onClick={() =>
                              copyAccessUrl(accessUrl, containerRow.id)
                            }
                          >
                            {copiedRowId === containerRow.id
                              ? 'Copied'
                              : copyFailedRowId === containerRow.id
                                ? 'Copy failed'
                                : 'Copy'}
                          </button>
                        ) : (
                          <span className="containers-muted" title="No Traefik route on this container">
                            —
                          </span>
                        )}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          aria-expanded={isExpanded}
                          aria-controls={`workloads-log-${containerRow.id}`}
                          onClick={() => toggleLogRow(containerRow.id)}
                        >
                          {isExpanded ? 'Hide' : 'Show'}
                        </button>
                      </td>
                      <td className="containers-table__actions">
                        <button
                          type="button"
                          className="btn btn--sm btn--ghost"
                          disabled={
                            rowBusyId === containerRow.id ||
                            containerRow.status === 'running'
                          }
                          onClick={() => void onStart(containerRow.id)}
                        >
                          Start
                        </button>
                        <button
                          type="button"
                          className="btn btn--sm btn--ghost"
                          disabled={
                            rowBusyId === containerRow.id ||
                            containerRow.status !== 'running'
                          }
                          onClick={() => void onStop(containerRow.id)}
                        >
                          Stop
                        </button>
                        <button
                          type="button"
                          className="btn btn--sm btn--danger"
                          disabled={rowBusyId === containerRow.id}
                          onClick={() => void onRemove(containerRow.id)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                    {isExpanded ? (
                      <tr className="workloads-table__expand-row">
                        <td colSpan={7}>
                          <div
                            id={`workloads-log-${containerRow.id}`}
                            className="workloads-table__expand-inner"
                          >
                            <ContainerLogPanel
                              containerId={containerRow.id}
                              isActive={isExpanded}
                              workloadStatus={containerRow.status}
                            />
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
