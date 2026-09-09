import { useCallback, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { ContainerInfo } from '../../api/client'
import type { WorkloadGroup } from '../../pages/containers/workloadGrouping'
import { workloadInstances } from '../../pages/containers/workloadGrouping'
import { WorkloadRow, type WorkloadStatsCellProps } from './WorkloadRow'
import { Skeleton } from '../Skeleton'

type WorkloadsTableProps = {
  listLoading: boolean
  groups: WorkloadGroup[]
  rowBusyId: string | null
  onStart: (containerId: string) => void
  onStop: (containerId: string) => void
  onRemove: (containerId: string) => void
  /** Open the per-container resource dashboard. */
  onViewResources?: (containerId: string) => void
  statsCell?: (row: WorkloadStatsCellProps) => ReactNode
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

function WorkloadStatsCell({
  group,
  instances,
  statsContainerId,
  statsExpanded,
  onToggleStats,
  onSelectStatsContainer,
}: WorkloadStatsCellProps) {
  const containerRow = group.base
  return (
    <>
      <label
        className="containers-form__label"
        htmlFor={`workloads-stats-select-${containerRow.id}`}
      >
        Instance
      </label>
      <select
        id={`workloads-stats-select-${containerRow.id}`}
        className="containers-form__input workloads-table__stats-select"
        aria-label={`Stats instance for ${containerRow.name}`}
        value={statsContainerId}
        onChange={(event) => onSelectStatsContainer(event.target.value)}
      >
        {instances.map((instance, index) => (
          <option key={instance.id} value={instance.id}>
            {index === 0 ? `${instance.name} (primary)` : instance.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn btn--ghost btn--sm"
        aria-expanded={statsExpanded}
        aria-controls={`workloads-stats-${containerRow.id}`}
        onClick={onToggleStats}
      >
        {statsExpanded ? 'Hide' : 'View'}
      </button>
    </>
  )
}

export function WorkloadsTable({
  listLoading,
  groups,
  rowBusyId,
  onStart,
  onStop,
  onRemove,
  onViewResources,
  statsCell,
}: WorkloadsTableProps) {
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
  const [terminalContainerId, setTerminalContainerId] = useState<string | null>(null)

  const columnCount = statsCell ? 9 : 8

  const toggleReplicaGroup = useCallback((groupId: string) => {
    setExpandedReplicaGroupId((current) =>
      current === groupId ? null : groupId,
    )
  }, [])

  const toggleStatsGroup = useCallback((groupId: string) => {
    setExpandedStatsGroupId((current) =>
      current === groupId ? null : groupId,
    )
  }, [])

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

  const handleSelectStatsContainer = useCallback(
    (groupId: string, containerId: string) => {
      setStatsContainerByGroup((previous) => ({
        ...previous,
        [groupId]: containerId,
      }))
      setExpandedStatsGroupId(groupId)
    },
    [],
  )

  const copyAccessUrl = useCallback((accessUrl: string, rowId: string) => {
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
  }, [])

  const toggleTerminal = useCallback((rowId: string) => {
    setTerminalContainerId((current) =>
      current === rowId ? null : rowId,
    )
  }, [])

  const closeTerminal = useCallback(() => {
    setTerminalContainerId(null)
  }, [])

  return (
    <div className="workloads-table-wrap-outer">
      {listLoading && groups.length === 0 ? (
        <div aria-busy="true" aria-label="Loading workloads">
          {[1, 2, 3].map((row) => (
            <Skeleton key={row} className="skeleton--team-row" />
          ))}
        </div>
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
                {statsCell ? <th>Stats</th> : null}
                <th>Logs</th>
                <th />
                <th className="workloads-table__expand-col" aria-label="Instances" />
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => {
                const containerRow = group.base
                const instances = workloadInstances(group)
                return (
                  <WorkloadRow
                    key={containerRow.id}
                    group={group}
                    rowBusyId={rowBusyId}
                    statsContainerId={resolvedStatsContainerId(group, instances)}
                    isReplicaExpanded={expandedReplicaGroupId === containerRow.id}
                    isStatsExpanded={expandedStatsGroupId === containerRow.id}
                    isCopied={copiedRowId === containerRow.id}
                    isCopyFailed={copyFailedRowId === containerRow.id}
                    isTerminalOpen={terminalContainerId === containerRow.id}
                    columnCount={columnCount}
                    statsCell={statsCell}
                    onToggleReplicas={toggleReplicaGroup}
                    onToggleStats={toggleStatsGroup}
                    onSelectStatsContainer={handleSelectStatsContainer}
                    onCopyUrl={copyAccessUrl}
                    onToggleTerminal={toggleTerminal}
                    onCloseTerminal={closeTerminal}
                    onStart={onStart}
                    onStop={onStop}
                    onRemove={onRemove}
                    onViewResources={onViewResources}
                  />
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

type DashboardWorkloadsTableProps = Omit<WorkloadsTableProps, 'statsCell'>

export function DashboardWorkloadsTable({
  listLoading,
  groups,
  rowBusyId,
  onStart,
  onStop,
  onRemove,
  onViewResources,
}: DashboardWorkloadsTableProps) {
  const displayGroups = useMemo(() => sortGroupsForDashboard(groups), [groups])
  const statsCell = useCallback(
    (row: WorkloadStatsCellProps) => <WorkloadStatsCell {...row} />,
    [],
  )
  return (
    <WorkloadsTable
      listLoading={listLoading}
      groups={displayGroups}
      rowBusyId={rowBusyId}
      onStart={onStart}
      onStop={onStop}
      onRemove={onRemove}
      onViewResources={onViewResources}
      statsCell={statsCell}
    />
  )
}
