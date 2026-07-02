import type { ContainerInfo, ScalingPolicyInfo } from '../../api/client'
import { VELA_REPLICA_OF_LABEL } from '../../api/client'

export type WorkloadGroup = {
  base: ContainerInfo
  replicas: ContainerInfo[]
  scalingPolicy: ScalingPolicyInfo | null
  /** True when auto-scaling is enabled for this deployment. */
  scalingEnabled: boolean
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

  return bases.map((base) => {
    const replicas = (replicasByBase.get(base.name) ?? []).sort((left, right) =>
      left.name.localeCompare(right.name),
    )
    const scalingPolicy = policyByName.get(base.name) ?? null
    return {
      base,
      replicas,
      scalingPolicy,
      scalingEnabled: scalingPolicy?.enabled === true,
    }
  })
}

export function workloadInstances(group: WorkloadGroup): ContainerInfo[] {
  return [group.base, ...group.replicas]
}
