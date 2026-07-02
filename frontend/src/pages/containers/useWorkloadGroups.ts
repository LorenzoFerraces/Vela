import { useCallback, useEffect, useState } from 'react'
import {
  formatApiError,
  listContainers,
  listScalingPolicies,
} from '../../api/client'
import { groupContainers, type WorkloadGroup } from './workloadGrouping'

export function useWorkloadGroups(reportLoadError: (detail: string) => void) {
  const [groups, setGroups] = useState<WorkloadGroup[]>([])
  const [listLoading, setListLoading] = useState(true)

  const refresh = useCallback(async () => {
    setListLoading(true)
    try {
      const [containers, policies] = await Promise.all([
        listContainers(),
        listScalingPolicies(),
      ])
      setGroups(groupContainers(containers, policies))
    } catch (error) {
      reportLoadError(formatApiError(error))
    } finally {
      setListLoading(false)
    }
  }, [reportLoadError])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { groups, listLoading, refresh }
}
