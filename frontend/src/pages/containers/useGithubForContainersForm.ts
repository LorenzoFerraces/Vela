import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  type GithubStatus,
  fetchAllGithubRepos,
  filterGithubReposByQuery,
  formatApiError,
  getGithubStatusWithRetry,
} from '../../api/client'
import { GITHUB_STATUS_DISCONNECTED } from './constants'
import type { GithubReposCacheState } from './types'

type AuthGate = {
  authStatus: string
  userId: string | undefined
}

export function useGithubForContainersForm({
  authStatus,
  userId,
}: AuthGate) {
  const [githubStatus, setGithubStatus] = useState<GithubStatus | null>(null)
  const [githubReposCache, setGithubReposCache] =
    useState<GithubReposCacheState>({ status: 'idle' })
  const [repoPickerOpen, setRepoPickerOpen] = useState(false)
  const [repoQuery, setRepoQuery] = useState('')

  useEffect(() => {
    let cancelled = false
    if (authStatus !== 'authenticated' || !userId) {
      queueMicrotask(() => {
        if (cancelled) return
        setGithubStatus(null)
        setGithubReposCache({ status: 'idle' })
        setRepoPickerOpen(false)
        setRepoQuery('')
      })
      return () => {
        cancelled = true
      }
    }
    queueMicrotask(() => {
      if (cancelled) return
      setGithubStatus(null)
    })
    void (async () => {
      try {
        const status = await getGithubStatusWithRetry()
        if (!cancelled) setGithubStatus(status)
      } catch {
        if (!cancelled) {
          setGithubStatus(GITHUB_STATUS_DISCONNECTED)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [authStatus, userId])

  useEffect(() => {
    function onVisible() {
      if (document.visibilityState !== 'visible') return
      if (authStatus !== 'authenticated' || !userId) return
      void getGithubStatusWithRetry()
        .then(setGithubStatus)
        .catch(() => {
          setGithubStatus(GITHUB_STATUS_DISCONNECTED)
        })
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [authStatus, userId])

  useEffect(() => {
    let cancelled = false
    if (!githubStatus?.connected) {
      queueMicrotask(() => {
        if (cancelled) return
        setGithubReposCache({ status: 'idle' })
      })
      return () => {
        cancelled = true
      }
    }
    queueMicrotask(() => {
      if (cancelled) return
      setGithubReposCache({ status: 'loading' })
      void fetchAllGithubRepos()
        .then((repos) => {
          if (!cancelled) {
            setGithubReposCache({ status: 'ok', repos })
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setGithubReposCache({
              status: 'error',
              detail: formatApiError(error),
            })
          }
        })
    })
    return () => {
      cancelled = true
    }
  }, [githubStatus?.connected])

  const filteredGithubRepos = useMemo(() => {
    if (githubReposCache.status !== 'ok') {
      return []
    }
    return filterGithubReposByQuery(githubReposCache.repos, repoQuery)
  }, [githubReposCache, repoQuery])

  const toggleRepoPicker = useCallback(() => {
    setRepoPickerOpen((open) => {
      if (open) {
        setRepoQuery('')
        return false
      }
      return true
    })
  }, [])

  return {
    githubStatus,
    githubReposCache,
    repoPickerOpen,
    repoQuery,
    setRepoQuery,
    filteredGithubRepos,
    toggleRepoPicker,
    setRepoPickerOpen,
  }
}
