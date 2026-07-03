import type { WorkloadGroup } from '../../pages/containers/workloadGrouping'
import { workloadInstances } from '../../pages/containers/workloadGrouping'
import { formatWorkloadHealth } from './formatWorkloadHealth'

type ReplicaInstancesPanelProps = {
  group: WorkloadGroup
}

export function ReplicaInstancesPanel({ group }: ReplicaInstancesPanelProps) {
  const instances = workloadInstances(group)
  return (
    <div className="workloads-replicas-panel">
      <p className="workloads-replicas-panel__lead">
        {group.scalingEnabled
          ? 'Auto-scaling is enabled'
          : 'Workload instances'}
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
