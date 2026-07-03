import { useCallback, useEffect, useRef, useState } from 'react'
import {
  formatApiError,
  listContainers,
  listScalingPolicies,
  type ScalingPolicyInfo,
} from '../../api/client'
import { groupContainers, type WorkloadGroup } from './workloadGrouping'

export function useWorkloadGroups(reportLoadError: (detail: string) => void) {
  const [groups, setGroups] = useState<WorkloadGroup[]>([])
  const [listLoading, setListLoading] = useState(true)
  const refreshGenerationRef = useRef(0)

  const refresh = useCallback(async () => {
    const generation = ++refreshGenerationRef.current
    setListLoading(true)
    try {
      let containers
      try {
        containers = await listContainers()
      } catch (error) {
        if (generation === refreshGenerationRef.current) {
          reportLoadError(formatApiError(error))
        }
        return
      }

      let policies: ScalingPolicyInfo[] = []
      try {
        policies = await listScalingPolicies()
      } catch {
        policies = []
      }

      if (generation !== refreshGenerationRef.current) {
        return
      }
      setGroups(groupContainers(containers, policies))
    } finally {
      if (generation === refreshGenerationRef.current) {
        setListLoading(false)
      }
    }
  }, [reportLoadError])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { groups, listLoading, refresh }
}
