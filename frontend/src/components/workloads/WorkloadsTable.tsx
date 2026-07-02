import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ContainerInfo, ContainerStats, ContainerStatus } from '../../api/client'
import {
  containerWriteAllowed,
  fetchContainerLogs,
  formatApiError,
  getContainerStats,
  openContainerLogWebSocket,
} from '../../api/client'
import { deploySourceImageLabel } from '../../pages/containers/deploySourceDisplay'
import type { WorkloadGroup } from '../../pages/containers/workloadGrouping'
import { workloadInstances } from '../../pages/containers/workloadGrouping'

const ERROR_LINE_PATTERN = /\b(error|exception|fatal|traceback)\b/i
const VIEWER_ACTION_DISABLED_TITLE =
  'Insufficient permissions to modify this workload (viewer role).'

type WorkloadsTableProps = {
  listLoading: boolean
  groups: WorkloadGroup[]
  rowBusyId: string | null
  onStart: (containerId: string) => void
  onStop: (containerId: string) => void
  onRemove: (containerId: string) => void
  /** When true, show containers that need attention first (dashboard). */
  prioritizeProblemWorkloads?: boolean
  /** When true, show a stats column with per-instance dropdown (dashboard). */
  showStatsColumn?: boolean
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

function sortGroupsForDashboard(groups: WorkloadGroup[]): WorkloadGroup[] {
  return [...groups].sort((groupA, groupB) => {
    const rankA = workloadConcernRank(groupA.base)
    const rankB = workloadConcernRank(groupB.base)
    if (rankA !== rankB) {
      return rankA - rankB
    }
    return groupA.base.name.localeCompare(groupB.base.name)
  })
}

function formatBytes(totalBytes: number): string {
  if (totalBytes < 1024) {
    return `${totalBytes} B`
  }
  if (totalBytes < 1024 * 1024) {
    return `${(totalBytes / 1024).toFixed(1)} KB`
  }
  return `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatWorkloadHealth(health: string): string {
  const normalized = health.trim().toLowerCase()
  switch (normalized) {
    case 'healthy':
      return 'Healthy'
    case 'unhealthy':
      return 'Unhealthy'
    case 'starting':
      return 'Starting'
    case 'none':
    case '':
      return 'Not configured'
    default:
      return health.trim() || 'Not configured'
  }
}

function aggregateStatus(group: WorkloadGroup): string {
  const instances = workloadInstances(group)
  const runningCount = instances.filter(
    (instance) => instance.status === 'running',
  ).length
  if (group.scalingEnabled) {
    const total = instances.length
    return `${runningCount}/${total} running`
  }
  return group.base.status
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
              <span
                key={key}
                className="workloads-log-panel__line workloads-log-panel__line--warn"
              >
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

function ContainerStatsPanel({
  containerId,
  isActive,
}: {
  containerId: string
  isActive: boolean
}) {
  const [stats, setStats] = useState<ContainerStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [errorText, setErrorText] = useState<string | null>(null)

  const refreshStats = useCallback(async () => {
    setLoading(true)
    try {
      const snapshot = await getContainerStats(containerId)
      setStats(snapshot)
      setErrorText(null)
    } catch (error) {
      setStats(null)
      setErrorText(formatApiError(error))
    } finally {
      setLoading(false)
    }
  }, [containerId])

  useEffect(() => {
    if (!isActive) {
      return
    }
    void refreshStats()
  }, [isActive, containerId, refreshStats])

  return (
    <div className="workloads-stats-panel">
      <div className="workloads-stats-panel__toolbar">
        <span className="workloads-stats-panel__status" role="status">
          {loading ? 'Loading stats…' : 'Current snapshot'}
        </span>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => void refreshStats()}
          disabled={loading}
        >
          Refresh
        </button>
      </div>
      {errorText ? (
        <p className="workloads-stats-panel__error" role="alert">
          {errorText}
        </p>
      ) : null}
      {stats ? (
        <dl className="workloads-stats-panel__grid">
          <div>
            <dt>CPU</dt>
            <dd>{stats.cpu_percent.toFixed(1)}%</dd>
          </div>
          <div>
            <dt>Memory</dt>
            <dd>
              {formatBytes(stats.memory_usage_bytes)}
              {stats.memory_limit_bytes > 0
                ? ` / ${formatBytes(stats.memory_limit_bytes)} (${stats.memory_percent.toFixed(1)}%)`
                : ''}
            </dd>
          </div>
          <div>
            <dt>Network in</dt>
            <dd>{formatBytes(stats.network_rx_bytes)}</dd>
          </div>
          <div>
            <dt>Network out</dt>
            <dd>{formatBytes(stats.network_tx_bytes)}</dd>
          </div>
        </dl>
      ) : null}
    </div>
  )
}

function ReplicaInstancesPanel({ group }: { group: WorkloadGroup }) {
  const instances = workloadInstances(group)
  return (
    <div className="workloads-replicas-panel">
      <p className="workloads-replicas-panel__lead">
        Auto-scaling is enabled
        {group.scalingPolicy
          ? ` (${group.scalingPolicy.min_replicas}–${group.scalingPolicy.max_replicas} replicas).`
          : '.'}
      </p>
      <table className="workloads-replicas-panel__table">
        <thead>
          <tr>
            <th>Instance</th>
            <th>Status</th>
            <th>Health</th>
          </tr>
        </thead>
        <tbody>
          {instances.map((instance, index) => (
            <tr key={instance.id}>
              <td>
                {index === 0 ? `${instance.name} (primary)` : instance.name}
              </td>
              <td>
                <span className="containers-status">{instance.status}</span>
              </td>
              <td>{formatWorkloadHealth(instance.health)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function WorkloadsTable({
  listLoading,
  groups,
  rowBusyId,
  onStart,
  onStop,
  onRemove,
  prioritizeProblemWorkloads = false,
  showStatsColumn = false,
}: WorkloadsTableProps) {
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null)
  const [expandedReplicaGroupId, setExpandedReplicaGroupId] = useState<
    string | null
  >(null)
  const [expandedStatsGroupId, setExpandedStatsGroupId] = useState<
    string | null
  >(null)
  const [statsContainerByGroup, setStatsContainerByGroup] = useState<
    Record<string, string>
  >({})
  const [copiedRowId, setCopiedRowId] = useState<string | null>(null)
  const [copyFailedRowId, setCopyFailedRowId] = useState<string | null>(null)

  const displayGroups = useMemo(
    () =>
      prioritizeProblemWorkloads ? sortGroupsForDashboard(groups) : groups,
    [prioritizeProblemWorkloads, groups],
  )

  const columnCount = showStatsColumn ? 9 : 8

  function toggleLogRow(containerId: string) {
    setExpandedLogId((current) =>
      current === containerId ? null : containerId,
    )
  }

  function toggleReplicaGroup(groupId: string) {
    setExpandedReplicaGroupId((current) =>
      current === groupId ? null : groupId,
    )
  }

  function toggleStatsGroup(groupId: string) {
    setExpandedStatsGroupId((current) =>
      current === groupId ? null : groupId,
    )
  }

  function statsContainerForGroup(group: WorkloadGroup): string {
    return statsContainerByGroup[group.base.id] ?? group.base.id
  }

  function setStatsContainerForGroup(group: WorkloadGroup, containerId: string) {
    setStatsContainerByGroup((previous) => ({
      ...previous,
      [group.base.id]: containerId,
    }))
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
      {listLoading && groups.length === 0 ? (
        <p className="containers-muted">Loading…</p>
      ) : groups.length === 0 ? (
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
                {showStatsColumn ? <th>Stats</th> : null}
                <th>Logs</th>
                <th />
                <th className="workloads-table__expand-col" aria-label="Instances" />
              </tr>
            </thead>
            <tbody>
              {displayGroups.map((group) => {
                const containerRow = group.base
                const isLogExpanded = expandedLogId === containerRow.id
                const isReplicaExpanded = expandedReplicaGroupId === containerRow.id
                const isStatsExpanded = expandedStatsGroupId === containerRow.id
                const accessUrl = containerRow.access_url?.trim() || ''
                const canModify = containerWriteAllowed(containerRow)
                const modifyDisabledTitle = canModify
                  ? undefined
                  : VIEWER_ACTION_DISABLED_TITLE
                const instances = workloadInstances(group)
                const statsContainerId = statsContainerForGroup(group)
                const statsTarget =
                  instances.find((instance) => instance.id === statsContainerId) ??
                  containerRow

                return (
                  <Fragment key={containerRow.id}>
                    <tr>
                      <td className="workloads-table__name-cell">
                        {containerRow.name}
                      </td>
                      <td
                        className="containers-table__mono"
                        title={
                          containerRow.source_kind === 'dockerfile_template' ||
                          containerRow.source_kind === 'git'
                            ? containerRow.image
                            : undefined
                        }
                      >
                        {deploySourceImageLabel(containerRow)}
                      </td>
                      <td>
                        <span className="containers-status">
                          {aggregateStatus(group)}
                        </span>
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
                          <span
                            className="containers-muted"
                            title="No Traefik route on this container"
                          >
                            —
                          </span>
                        )}
                      </td>
                      {showStatsColumn ? (
                        <td className="workloads-table__stats-cell">
                          <select
                            className="containers-form__input workloads-table__stats-select"
                            aria-label={`Stats instance for ${containerRow.name}`}
                            value={statsContainerId}
                            onChange={(event) => {
                              setStatsContainerForGroup(
                                group,
                                event.target.value,
                              )
                              setExpandedStatsGroupId(containerRow.id)
                            }}
                          >
                            {instances.map((instance, index) => (
                              <option key={instance.id} value={instance.id}>
                                {index === 0
                                  ? `${instance.name} (primary)`
                                  : instance.name}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            aria-expanded={isStatsExpanded}
                            aria-controls={`workloads-stats-${containerRow.id}`}
                            onClick={() => toggleStatsGroup(containerRow.id)}
                          >
                            {isStatsExpanded ? 'Hide' : 'View'}
                          </button>
                        </td>
                      ) : null}
                      <td>
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          aria-expanded={isLogExpanded}
                          aria-controls={`workloads-log-${containerRow.id}`}
                          onClick={() => toggleLogRow(containerRow.id)}
                        >
                          {isLogExpanded ? 'Hide' : 'Show'}
                        </button>
                      </td>
                      <td className="containers-table__actions">
                        <button
                          type="button"
                          className="btn btn--sm btn--ghost"
                          title={modifyDisabledTitle}
                          aria-label={
                            canModify
                              ? 'Start container'
                              : `Start container — ${VIEWER_ACTION_DISABLED_TITLE}`
                          }
                          disabled={
                            !canModify ||
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
                          title={modifyDisabledTitle}
                          aria-label={
                            canModify
                              ? 'Stop container'
                              : `Stop container — ${VIEWER_ACTION_DISABLED_TITLE}`
                          }
                          disabled={
                            !canModify ||
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
                          title={modifyDisabledTitle}
                          aria-label={
                            canModify
                              ? 'Remove container'
                              : `Remove container — ${VIEWER_ACTION_DISABLED_TITLE}`
                          }
                          disabled={!canModify || rowBusyId === containerRow.id}
                          onClick={() => void onRemove(containerRow.id)}
                        >
                          Remove
                        </button>
                      </td>
                      <td className="workloads-table__expand-cell">
                        {group.scalingEnabled ? (
                          <button
                            type="button"
                            className="workloads-table__expand-toggle"
                            aria-expanded={isReplicaExpanded}
                            aria-controls={`workloads-replicas-${containerRow.id}`}
                            aria-label={
                              isReplicaExpanded
                                ? `Hide ${instances.length} instances`
                                : `Show ${instances.length} instances`
                            }
                            onClick={() => toggleReplicaGroup(containerRow.id)}
                          >
                            <span
                              className="workloads-table__expand-chevron"
                              aria-hidden="true"
                            >
                              ›
                            </span>
                          </button>
                        ) : null}
                      </td>
                    </tr>
                    {group.scalingEnabled && isReplicaExpanded ? (
                      <tr className="workloads-table__expand-row">
                        <td colSpan={columnCount}>
                          <div
                            id={`workloads-replicas-${containerRow.id}`}
                            className="workloads-table__expand-inner"
                          >
                            <ReplicaInstancesPanel group={group} />
                          </div>
                        </td>
                      </tr>
                    ) : null}
                    {showStatsColumn && isStatsExpanded ? (
                      <tr className="workloads-table__expand-row">
                        <td colSpan={columnCount}>
                          <div
                            id={`workloads-stats-${containerRow.id}`}
                            className="workloads-table__expand-inner"
                          >
                            <ContainerStatsPanel
                              containerId={statsTarget.id}
                              isActive={isStatsExpanded}
                            />
                          </div>
                        </td>
                      </tr>
                    ) : null}
                    {isLogExpanded ? (
                      <tr className="workloads-table__expand-row">
                        <td colSpan={columnCount}>
                          <div
                            id={`workloads-log-${containerRow.id}`}
                            className="workloads-table__expand-inner"
                          >
                            <ContainerLogPanel
                              containerId={containerRow.id}
                              isActive={isLogExpanded}
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
