/**
 * Container management API endpoints for the Vela application.
 */
import { apiDelete, apiGet, apiPatch, apiPost, apiRequest, apiUploadFile } from '../client'
import { ContainerInfo, ContainerStatus, PortMapping, RunFromSourceRequest, RunFromSourceResponse, RunSourceKind, VolumeMountRequest, VolumeUploadResponse } from './types'

export type ProjectRole = 'owner' | 'operator' | 'viewer'

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

export type RunSourceKind = 'image' | 'git' | 'dockerfile_template'

export interface VolumeUploadResponse {
  upload_id: string
  folder_name: string
  total_bytes: number
  file_count: number
  max_bytes: number
  user_quota_bytes: number
  user_used_bytes: number
}

export interface VolumeMountRequest {
  upload_id: string
  target: string
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
}

export interface RunFromSourceResponse {
  container: ContainerInfo
  kind: RunSourceKind
  image: string
  route_wired: boolean
  public_url?: string | null
}

export async function listContainers(): Promise<ContainerInfo[]> {
  return apiGet<ContainerInfo[]>('/api/containers/')
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

export async function getContainerLogs(
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

export async function getContainerStatus(
  containerId: string
): Promise<ContainerInfo> {
  return apiGet<ContainerInfo>(`/api/containers/${encodeURIComponent(containerId)}`)
}