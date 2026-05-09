import type { GithubRepo } from '../../api/client'

export type FormMessage = {
  type: 'ok' | 'err'
  text: string
  publicUrl?: string
}

export type GithubReposCacheState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ok'; repos: GithubRepo[] }
  | { status: 'error'; detail: string }

export type ImageRefCheckState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'ok'; ref: string }
  | {
      status: 'unavailable'
      ref: string
      /** When true, registry returned 401/403; user may still try Build after `docker login`. */
      canAttemptDeploy: boolean
    }
  | { status: 'error'; detail: string }
