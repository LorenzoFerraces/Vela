import { useCallback, useEffect, useState } from 'react'
import { listActiveDeploys, type DeployJob } from '../api/client'

const DEPLOY_POLL_INTERVAL_MS = 2500

/**
 * Polls GET /api/deploys/active: once on mount (restores in-flight jobs
 * after reload/route change), then every 2.5s while any returned job is
 * in_progress; paused while the tab is hidden. Errors keep the last state.
 */
export function useActiveDeployJobs(): {
  jobs: DeployJob[]
  refresh: () => Promise<void>
} {
  const [jobs, setJobs] = useState<DeployJob[]>([])
  const anyInFlight = jobs.some((job) => job.status === 'in_progress')

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
    if (!anyInFlight) return
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
  }, [anyInFlight, refresh])

  return { jobs, refresh }
}
