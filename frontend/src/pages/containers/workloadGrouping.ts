import type { ContainerInfo, ScalingPolicyInfo } from '../../api/client'
import { VELA_REPLICA_OF_LABEL } from '../../api/client'

export type WorkloadGroup = {
  base: ContainerInfo
  replicas: ContainerInfo[]
  scalingPolicy: ScalingPolicyInfo | null
  /** True when auto-scaling is enabled for this deployment. */
  scalingEnabled: boolean
}

function buildWorkloadGroup(
  base: ContainerInfo,
  replicas: ContainerInfo[],
  policyByName: Map<string, ScalingPolicyInfo>,
): WorkloadGroup {
  const scalingPolicy = policyByName.get(base.name) ?? null
  return {
    base,
    replicas,
    scalingPolicy,
    scalingEnabled: scalingPolicy?.enabled === true,
  }
}

export function groupContainers(
  containers: ContainerInfo[],
  policies: ScalingPolicyInfo[],
): WorkloadGroup[] {
  const policyByName = new Map(
    policies.map((policy) => [policy.container_name, policy]),
  )
  const replicasByBase = new Map<string, ContainerInfo[]>()
  const bases: ContainerInfo[] = []

  for (const container of containers) {
    const replicaOf = container.labels[VELA_REPLICA_OF_LABEL]?.trim()
    if (replicaOf) {
      const existing = replicasByBase.get(replicaOf) ?? []
      existing.push(container)
      replicasByBase.set(replicaOf, existing)
      continue
    }
    bases.push(container)
  }

  const baseNames = new Set(bases.map((base) => base.name))
  const groups = bases.map((base) => {
    const replicas = (replicasByBase.get(base.name) ?? []).sort((left, right) =>
      left.name.localeCompare(right.name),
    )
    return buildWorkloadGroup(base, replicas, policyByName)
  })

  const orphanReplicas = containers.filter((container) => {
    const replicaOf = container.labels[VELA_REPLICA_OF_LABEL]?.trim()
    return Boolean(replicaOf) && !baseNames.has(replicaOf)
  })

  for (const orphan of orphanReplicas.sort((left, right) =>
    left.name.localeCompare(right.name),
  )) {
    groups.push(buildWorkloadGroup(orphan, [], policyByName))
  }

  return groups
}

export function workloadInstances(group: WorkloadGroup): ContainerInfo[] {
  return [group.base, ...group.replicas]
}
