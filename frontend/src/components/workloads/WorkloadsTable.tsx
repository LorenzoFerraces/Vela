import { Fragment, useMemo, useState } from 'react'
import type { ContainerInfo } from '../../api/client'
import { containerWriteAllowed } from '../../api/client'
import { deploySourceImageLabel } from '../../pages/containers/deploySourceDisplay'
import type { WorkloadGroup } from '../../pages/containers/workloadGrouping'
import { workloadInstances } from '../../pages/containers/workloadGrouping'
import { ContainerLogPanel } from './ContainerLogPanel'
import { ContainerStatsPanel } from './ContainerStatsPanel'
import { ReplicaInstancesPanel } from './ReplicaInstancesPanel'

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

function showsInstanceSummary(group: WorkloadGroup): boolean {
  return group.replicas.length > 0 || group.scalingEnabled
}

function aggregateStatus(group: WorkloadGroup): string {
  const instances = workloadInstances(group)
  const runningCount = instances.filter(
    (instance) => instance.status === 'running',
  ).length
  if (showsInstanceSummary(group)) {
    return `${runningCount}/${instances.length} running`
  }
  return group.base.status
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

  function resolvedStatsContainerId(
    group: WorkloadGroup,
    instances: ContainerInfo[],
  ): string {
    const storedId = statsContainerByGroup[group.base.id]
    if (storedId && instances.some((instance) => instance.id === storedId)) {
      return storedId
    }
    return group.base.id
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
                const statsContainerId = resolvedStatsContainerId(group, instances)
                const statsTarget =
                  instances.find((instance) => instance.id === statsContainerId) ??
                  containerRow
                const showReplicaControls = showsInstanceSummary(group)

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
