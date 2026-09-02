import { Fragment, lazy, memo, Suspense, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { ContainerInfo } from '../../api/client'
import { containerWriteAllowed } from '../../api/client'
import { deploySourceImageLabel } from '../../pages/containers/deploySourceDisplay'
import type { WorkloadGroup } from '../../pages/containers/workloadGrouping'
import { workloadInstances } from '../../pages/containers/workloadGrouping'
import { ContainerStatsPanel } from './ContainerStatsPanel'
import { ReplicaInstancesPanel } from './ReplicaInstancesPanel'

// ponytail: lazy so xterm stays out of the first-paint chunk (terminal is opt-in per row)
const ContainerTerminal = lazy(() =>
  import('./ContainerTerminal').then((module) => ({
    default: module.ContainerTerminal,
  })),
)

const VIEWER_ACTION_DISABLED_TITLE =
  'Insufficient permissions to modify this workload (viewer role).'

export type WorkloadStatsCellProps = {
  group: WorkloadGroup
  instances: ContainerInfo[]
  statsContainerId: string
  statsExpanded: boolean
  onToggleStats: () => void
  onSelectStatsContainer: (containerId: string) => void
}

function showsInstanceSummary(group: WorkloadGroup): boolean {
  return group.replicas.length > 0 || group.scalingEnabled
}

function aggregateStatus(group: WorkloadGroup, instances: ContainerInfo[]): string {
  const runningCount = instances.filter(
    (instance) => instance.status === 'running',
  ).length
  if (showsInstanceSummary(group)) {
    return `${runningCount}/${instances.length} running`
  }
  return group.base.status
}

function statusIsLive(group: WorkloadGroup, instances: ContainerInfo[]): boolean {
  if (showsInstanceSummary(group)) {
    return instances.some((instance) => instance.status === 'running')
  }
  return group.base.status === 'running'
}

type WorkloadRowProps = {
  group: WorkloadGroup
  rowBusyId: string | null
  statsContainerId: string
  isReplicaExpanded: boolean
  isStatsExpanded: boolean
  isCopied: boolean
  isCopyFailed: boolean
  isTerminalOpen: boolean
  columnCount: number
  statsCell?: (row: WorkloadStatsCellProps) => ReactNode
  onToggleReplicas: (groupId: string) => void
  onToggleStats: (groupId: string) => void
  onSelectStatsContainer: (groupId: string, containerId: string) => void
  onCopyUrl: (accessUrl: string, rowId: string) => void
  onToggleTerminal: (rowId: string) => void
  onCloseTerminal: () => void
  onStart: (containerId: string) => void
  onStop: (containerId: string) => void
  onRemove: (containerId: string) => void
}

function WorkloadRowBase({
  group,
  rowBusyId,
  statsContainerId,
  isReplicaExpanded,
  isStatsExpanded,
  isCopied,
  isCopyFailed,
  isTerminalOpen,
  columnCount,
  statsCell,
  onToggleReplicas,
  onToggleStats,
  onSelectStatsContainer,
  onCopyUrl,
  onToggleTerminal,
  onCloseTerminal,
  onStart,
  onStop,
  onRemove,
}: WorkloadRowProps) {
  const containerRow = group.base
  const accessUrl = containerRow.access_url?.trim() || ''
  const canModify = containerWriteAllowed(containerRow)
  const modifyDisabledTitle = canModify
    ? undefined
    : VIEWER_ACTION_DISABLED_TITLE
  const instances = workloadInstances(group)
  const statusText = aggregateStatus(group, instances)
  const statsTarget =
    instances.find((instance) => instance.id === statsContainerId) ??
    containerRow
  const showReplicaControls = showsInstanceSummary(group)

  return (
    <Fragment>
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
          <span
            className={
              statusIsLive(group, instances)
                ? 'containers-status containers-status--live'
                : 'containers-status'
            }
          >
            {statusText}
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
              onClick={() => onCopyUrl(accessUrl, containerRow.id)}
            >
              {isCopied
                ? 'Copied'
                : isCopyFailed
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
        {statsCell ? (
          <td className="workloads-table__stats-cell">
            {statsCell({
              group,
              instances,
              statsContainerId,
              statsExpanded: isStatsExpanded,
              onToggleStats: () => onToggleStats(containerRow.id),
              onSelectStatsContainer: (containerId) =>
                onSelectStatsContainer(containerRow.id, containerId),
            })}
          </td>
        ) : null}
        <td>
          <Link
            to={`/logs?container_id=${encodeURIComponent(containerRow.id)}`}
            className="btn btn--ghost btn--sm"
            title="View logs"
            aria-label="View logs"
          >
            Logs
          </Link>
        </td>
        <td className="containers-table__actions">
          {containerRow.status === 'running' && canModify ? (
            <button
              type="button"
              className="btn btn--sm btn--ghost"
              title="Open terminal"
              aria-label="Open terminal"
              aria-expanded={isTerminalOpen}
              aria-controls={`workloads-terminal-${containerRow.id}`}
              onClick={() => onToggleTerminal(containerRow.id)}
            >
              {'>'}
            </button>
          ) : null}
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
          {showReplicaControls ? (
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
              onClick={() => onToggleReplicas(containerRow.id)}
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
      {showReplicaControls && isReplicaExpanded ? (
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
      {statsCell && isStatsExpanded ? (
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
      {isTerminalOpen ? (
        <tr className="workloads-table__expand-row">
          <td colSpan={columnCount}>
            <div
              id={`workloads-terminal-${containerRow.id}`}
              className="workloads-table__expand-inner"
            >
              <Suspense
                fallback={
                  <div className="skeleton" style={{ minHeight: 320 }} />
                }
              >
                <ContainerTerminal
                  containerId={containerRow.id}
                  onClose={onCloseTerminal}
                />
              </Suspense>
            </div>
          </td>
        </tr>
      ) : null}
    </Fragment>
  )
}

export const WorkloadRow = memo(WorkloadRowBase)
