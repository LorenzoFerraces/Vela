import { useCallback, useEffect, useRef, useState } from 'react'
import {
  formatApiError,
  listContainers,
  listScalingPolicies,
  type ScalingPolicyInfo,
} from '../../api/client'
import { groupContainers, type WorkloadGroup } from './workloadGrouping'

const POLL_INTERVAL_MS = 30_000

export function useWorkloadGroups(reportLoadError: (detail: string) => void) {
  const [groups, setGroups] = useState<WorkloadGroup[]>([])
  const [listLoading, setListLoading] = useState(true)
  const refreshGenerationRef = useRef(0)

  const refresh = useCallback(async (options: { revalidate?: boolean } = {}) => {
    const generation = ++refreshGenerationRef.current
    setListLoading(true)
    try {
      let containers
      try {
        containers = await listContainers(options)
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

  useEffect(() => {
    let pollTimer: number | undefined

    const stopPolling = () => {
      if (pollTimer !== undefined) {
        window.clearInterval(pollTimer)
        pollTimer = undefined
      }
    }

    const startPolling = () => {
      stopPolling()
      pollTimer = window.setInterval(() => {
        void refresh({ revalidate: true })
      }, POLL_INTERVAL_MS)
    }

    function onVisibilityChange() {
      if (document.visibilityState === 'visible') {
        void refresh({ revalidate: true })
        startPolling()
      } else {
        stopPolling()
      }
    }

    if (document.visibilityState === 'visible') {
      startPolling()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [refresh])

  return { groups, listLoading, refresh }
}
