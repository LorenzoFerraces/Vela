/**
 * Async deploy jobs: submit returns 202 {job_id}; progress and terminal
 * state come from GET /api/deploys/active (polled while in flight).
 */
import { apiGet, apiPost } from './core'
import type { RunFromSourceRequest } from './containers'

export type DeployJobKind = 'container' | 'stack'
export type DeployJobStatus = 'in_progress' | 'succeeded' | 'failed'
export type DeployServiceState =
  | 'pending'
  | 'building'
  | 'starting'
  | 'running'
  | 'failed'

export interface DeployServiceProgress {
  name: string
  state: DeployServiceState
}

export interface DeployJobError {
  code: string
  detail: string
  build_log?: string | null
  failed_service?: string | null
}

export interface DeployJob {
  job_id: string
  kind: DeployJobKind
  project_id: string
  name: string
  source_label: string
  status: DeployJobStatus
  phase: string
  phase_detail: string | null
  services: DeployServiceProgress[]
  error: DeployJobError | null
  result: Record<string, unknown> | null
  created_at: string
  finished_at: string | null
}

export interface DeployAccepted {
  job_id: string
  status: 'in_progress'
}

export function listActiveDeploys(): Promise<DeployJob[]> {
  return apiGet<DeployJob[]>('/api/deploys/active')
}

export function submitRun(body: RunFromSourceRequest): Promise<DeployAccepted> {
  return apiPost<DeployAccepted, RunFromSourceRequest>(
    '/api/containers/run',
    body,
  )
}
