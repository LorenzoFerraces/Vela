import { apiGet, apiPatch, apiPost, type RunSourceKind } from './core'

export type BuildOverrideLanguage =
  | 'python'
  | 'javascript'
  | 'typescript'
  | 'go'
  | 'java'
  | 'rust'
  | 'ruby'
  | 'php'
  | 'dotnet'
  | 'elixir'
  | 'clojure'

export type BuildOverride = {
  language: BuildOverrideLanguage
  language_version?: string | null
  package_manager?: string | null
  build_subdir?: string | null
  start_command?: string[] | null
}

export type GitSourceAnalysis = {
  git_branch: string | null
  container_port: number
  container_name: string | null
  env_vars: Record<string, string>
  start_command: string[] | null
  language: string | null
  framework: string | null
  has_dockerfile: boolean
  build_strategy: 'dockerfile_exists' | 'generated_dockerfile'
  summary_hint: string
  build_subdir: string | null
  needs_manual_build_config: boolean
}

export async function analyzeGitSource(body: {
  git_url: string
  git_branch: string
  use_server_default?: boolean
}): Promise<GitSourceAnalysis> {
  return apiPost<GitSourceAnalysis, typeof body>(
    '/api/builder/analyze-source',
    body
  )
}

export type DeploymentRecord = {
  id: string
  user_id: string
  author_email: string
  container_id: string
  container_name: string | null
  source_kind: RunSourceKind
  source_ref: string
  git_branch: string | null
  image_tag: string
  container_port: number
  env_vars: Record<string, string>
  command: string[] | null
  dockerfile_snapshot: string | null
  public_url: string | null
  created_at: string
  build_override?: BuildOverride | null
}

export type DeploymentEnvDiff = {
  added: Record<string, string>
  removed: Record<string, string>
  changed: Record<string, { before: string; after: string }>
}

export type DeploymentDiffResponse = {
  left_id: string
  right_id: string
  env: DeploymentEnvDiff
  dockerfile_diff: string[]
}

export type DeploymentUpdateRequest = {
  env_vars?: Record<string, string> | null
  command?: string[] | null
  labels?: Record<string, string> | null
  health_check?: {
    command: string[]
    interval_s?: number
    timeout_s?: number
    retries?: number
    start_period_s?: number
  } | null
  cpu_limit?: number | null
  memory_limit?: number | null
  route_host?: string | null
  route_path_prefix?: string | null
  route_tls?: boolean | null
  public_route?: boolean | null
}

export type ConfigFieldDiff = {
  before: unknown
  after: unknown
}

export type DeploymentUpdateDryRunResponse = DeploymentDiffResponse & {
  /** Proposed values of changed mutable fields; secret values are never included. */
  config: Record<string, unknown>
}

export async function listDeployments(options: {
  container_name?: string
  limit?: number
} = {}): Promise<DeploymentRecord[]> {
  const params = new URLSearchParams()
  if (options.container_name) {
    params.set('container_name', options.container_name)
  }
  if (options.limit != null) {
    params.set('limit', String(options.limit))
  }
  const query = params.toString()
  return apiGet<DeploymentRecord[]>(
    query ? `/api/deployments/?${query}` : '/api/deployments/'
  )
}

export async function getDeploymentDiff(
  leftId: string,
  rightId: string
): Promise<DeploymentDiffResponse> {
  return apiGet<DeploymentDiffResponse>(
    `/api/deployments/${encodeURIComponent(leftId)}/diff/${encodeURIComponent(rightId)}`
  )
}

export async function dryRunDeployment(
  id: string,
  body: DeploymentUpdateRequest
): Promise<DeploymentUpdateDryRunResponse> {
  return apiPost<DeploymentUpdateDryRunResponse, DeploymentUpdateRequest>(
    `/api/deployments/${encodeURIComponent(id)}/dry-run`,
    body
  )
}

export async function updateDeployment(
  id: string,
  body: DeploymentUpdateRequest
): Promise<DeploymentRecord> {
  return apiPatch<DeploymentRecord, DeploymentUpdateRequest>(
    `/api/deployments/${encodeURIComponent(id)}`,
    body
  )
}
