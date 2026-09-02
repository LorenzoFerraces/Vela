import {
  ApiError,
  apiDelete,
  apiGet,
  apiPost,
  clearAccessToken,
  getAccessToken,
  getApiBaseUrl,
  getApiWebSocketUrl,
  notifyUnauthorized,
  type ProjectRole,
  type RunSourceKind,
  type VolumeMountRequest,
} from './core'
import { type BuildOverride } from './builds'
import { type ScalingPolicyInfo, type ScalingPolicyRequest } from './scaling'

export type ContainerStatus =
  | 'created'
  | 'running'
  | 'paused'
  | 'restarting'
  | 'stopped'
  | 'dead'
  | 'unknown'

export interface PortMapping {
  host_port: number
  container_port: number
  protocol: string
}

export interface ContainerInfo {
  id: string
  name: string
  image: string
  status: ContainerStatus
  created_at: string
  ports: PortMapping[]
  labels: Record<string, string>
  health: string
  /** Public edge URL when Traefik route labels are present on the container. */
  access_url?: string | null
  /** From vela.source_kind label when the workload was deployed via the run API. */
  source_kind?: RunSourceKind | null
  /** User-facing source (template name, image ref, Git URL) from vela.source_ref. */
  source_label?: string | null
  /** Caller's role for this container's project. */
  access_role?: ProjectRole | null
}

export const VELA_REPLICA_OF_LABEL = 'vela.replica_of'

export interface ContainerStats {
  container_id: string
  timestamp: string
  cpu_percent: number
  memory_usage_bytes: number
  memory_limit_bytes: number
  memory_percent: number
  network_rx_bytes: number
  network_tx_bytes: number
}

export interface RunFromSourceRequest {
  source_kind?: RunSourceKind
  source?: string
  image_ref?: string
  git_url?: string
  dockerfile_template_id?: string
  container_name?: string | null
  host_port?: number | null
  container_port?: number
  git_branch?: string
  route_host?: string | null
  route_path_prefix?: string
  route_tls?: boolean
  public_route?: boolean
  env_vars?: Record<string, string>
  command?: string[] | null
  project_id?: string | null
  volumes?: VolumeMountRequest[]
  scaling_policy?: ScalingPolicyRequest | null
  build_override?: BuildOverride | null
}

export interface RunFromSourceResponse {
  container: ContainerInfo
  kind: RunSourceKind
  image: string
  route_wired: boolean
  public_url?: string | null
  scaling_policy?: ScalingPolicyInfo | null
  scaling_policy_warning?: string | null
}

export interface VolumeUploadResponse {
  upload_id: string
  folder_name: string
  total_bytes: number
  file_count: number
  max_bytes: number
  user_quota_bytes: number
  user_used_bytes: number
}

export type DeploySourceSuggestion =
  | { kind: 'image'; ref: string; label: string }
  | {
    kind: 'git'
    url: string
    name: string
    default_branch: string
  }
  | { kind: 'dockerfile_template'; id: string; name: string }

export async function listContainers(): Promise<ContainerInfo[]> {
  return apiGet<ContainerInfo[]>('/api/containers/', { cache: true })
}

export async function getContainerStats(containerId: string): Promise<ContainerStats> {
  return apiGet<ContainerStats>(
    `/api/containers/${encodeURIComponent(containerId)}/stats`,
  )
}

const MAX_CONTAINER_LOG_TAIL = 2000
const textEncoder = new TextEncoder()

export type ContainerLogWebSocketOptions = {
  tail?: number
  follow?: boolean
}

/**
 * Open an authenticated WebSocket for live container logs.
 * Pass `access_token` query param (required for browser WebSocket auth).
 */
export function openContainerLogWebSocket(
  containerId: string,
  options: ContainerLogWebSocketOptions = {}
): WebSocket {
  const token = getAccessToken()
  if (!token) {
    throw new Error('Sign in to view logs.')
  }
  const tail =
    options.tail != null
      ? Math.min(Math.max(1, options.tail), MAX_CONTAINER_LOG_TAIL)
      : 400
  const params = new URLSearchParams({
    access_token: token,
    tail: String(tail),
  })
  if (options.follow === false) {
    params.set('follow', 'false')
  }
  const path = `/api/containers/${encodeURIComponent(containerId)}/logs/stream?${params.toString()}`
  return new WebSocket(getApiWebSocketUrl(path))
}

export interface ExecWebSocketHandle {
  send: (data: string | Uint8Array) => void
  dispose: () => void
}

export function openContainerExecWebSocket(
  containerId: string,
  onOpen: () => void,
  onMessage: (data: Uint8Array) => void,
  onClose: () => void,
  onError: () => void,
): ExecWebSocketHandle {
  const token = getAccessToken()
  if (!token) {
    throw new Error('Sign in to open a terminal.')
  }
  const params = new URLSearchParams({ access_token: token })
  const path = `/api/containers/${encodeURIComponent(containerId)}/exec/ws?${params.toString()}`
  const ws = new WebSocket(getApiWebSocketUrl(path))
  ws.binaryType = 'arraybuffer'

  ws.onopen = () => onOpen()
  ws.onmessage = (event) => {
    const data =
      typeof event.data === 'string'
        ? textEncoder.encode(event.data)
        : new Uint8Array(event.data)
    onMessage(data)
  }
  ws.onclose = () => onClose()
  ws.onerror = () => onError()

  return {
    send: (data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data)
    },
    dispose: () => ws.close(),
  }
}

export async function fetchContainerLogs(
  containerId: string,
  options: { tail?: number } = {}
): Promise<string> {
  const tail =
    options.tail != null
      ? Math.min(Math.max(1, options.tail), MAX_CONTAINER_LOG_TAIL)
      : 200
  const query = new URLSearchParams({ tail: String(tail) })
  const data = await apiGet<{ logs: string }>(
    `/api/containers/${encodeURIComponent(containerId)}/logs?${query.toString()}`
  )
  return data.logs
}

export async function runContainerFromSource(
  body: RunFromSourceRequest
): Promise<RunFromSourceResponse> {
  return apiPost<RunFromSourceResponse, RunFromSourceRequest>(
    '/api/containers/run',
    body
  )
}

export async function uploadVolumeFolder(
  files: File[]
): Promise<VolumeUploadResponse> {
  const formData = new FormData()
  for (const file of files) {
    const relativePath = file.webkitRelativePath || file.name
    formData.append('files', file, relativePath)
  }

  const url = `${getApiBaseUrl()}/api/containers/volume-uploads`
  const headers = new Headers()
  headers.set('Accept', 'application/json')
  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(url, {
    method: 'POST',
    body: formData,
    headers,
  })

  if (!response.ok) {
    const body = await response.text()
    if (response.status === 401) {
      clearAccessToken()
      notifyUnauthorized()
    }
    throw new ApiError(
      `Request failed: ${response.status} ${response.statusText}`,
      response.status,
      body
    )
  }

  const text = await response.text()
  if (!text) {
    throw new ApiError('Empty upload response', response.status, '')
  }
  return JSON.parse(text) as VolumeUploadResponse
}

/**
 * Fetches deploy source suggestions that match the provided query.
 *
 * @param query - Search string used to find matching deploy sources
 * @param options - Optional parameters for the request
 * @param options.limit - Maximum number of suggestions to return
 * @returns An array of DeploySourceSuggestion objects matching the query
 */
export async function getDeploySourceSuggestions(
  query: string,
  options: { limit?: number } = {}
): Promise<{
  suggestions: DeploySourceSuggestion[]
  pasted_github_hint: string | null
}> {
  const params = new URLSearchParams({ q: query })
  if (options.limit != null) {
    params.set('limit', String(options.limit))
  }
  const data = await apiGet<{
    suggestions: DeploySourceSuggestion[]
    pasted_github_hint?: string | null
  }>(`/api/containers/deploy-sources?${params.toString()}`)
  return {
    suggestions: data.suggestions,
    pasted_github_hint: data.pasted_github_hint ?? null,
  }
}

export async function startContainer(containerId: string): Promise<ContainerInfo> {
  return apiPost<ContainerInfo>(`/api/containers/${encodeURIComponent(containerId)}/start`, {})
}

export async function stopContainer(containerId: string): Promise<ContainerInfo> {
  return apiPost<ContainerInfo>(`/api/containers/${encodeURIComponent(containerId)}/stop`, {})
}

export async function removeContainer(
  containerId: string,
  force = false
): Promise<void> {
  const q = force ? '?force=true' : ''
  await apiDelete(
    `/api/containers/${encodeURIComponent(containerId)}${q}`
  )
}

export function containerWriteAllowed(container: ContainerInfo): boolean {
  return container.access_role === 'owner' || container.access_role === 'operator'
}
