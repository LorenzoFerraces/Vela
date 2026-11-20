import { useCallback, useEffect, useMemo, useState } from 'react'
import { listActiveDeploys, type DeployJob } from '../api/client'

const DEPLOY_POLL_INTERVAL_MS = 1000

/**
 * Polls GET /api/deploys/active once on mount and every second while the tab
 * is visible, so jobs submitted via the API or another tab show up here.
 * Errors keep the last state.
 */
export function useActiveDeployJobs(): {
  jobs: DeployJob[]
  hasInFlightJob: boolean
  refresh: () => Promise<void>
} {
  const [jobs, setJobs] = useState<DeployJob[]>([])

  const refresh = useCallback(() => {
    return listActiveDeploys()
      .then(setJobs)
      .catch(() => {
        // transient poll failure — keep the last known state
      })
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') void refresh()
    }, DEPLOY_POLL_INTERVAL_MS)
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [refresh])

  const hasInFlightJob = useMemo(
    () => jobs.some((job) => job.status === 'in_progress'),
    [jobs],
  )

  return { jobs, hasInFlightJob, refresh }
}
