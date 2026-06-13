/**
 * Thin HTTP client for the Vela FastAPI backend.
 * Base URL: `VITE_API_BASE_URL` or `window.location.hostname:8000`
 */

function getDefaultBaseUrl(): string {
  if (typeof window === 'undefined') {
    return 'http://localhost:8000'
  }

  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:'
  return `${protocol}//${window.location.hostname}:8000`
}

export function getApiBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_API_BASE_URL
  return typeof fromEnv === 'string' && fromEnv.length > 0
    ? fromEnv.replace(/\/$/, '')
    : getDefaultBaseUrl()
}

// --- Access token storage ---

const ACCESS_TOKEN_STORAGE_KEY = 'vela.access_token'

export function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setAccessToken(token: string): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token)
  } catch {
    // localStorage is unavailable (private mode, etc.); silently skip persistence.
  }
}

export function clearAccessToken(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY)
  } catch {
    // see setAccessToken
  }
}

type UnauthorizedListener = () => void
const unauthorizedListeners = new Set<UnauthorizedListener>()

export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

function notifyUnauthorized(): void {
  unauthorizedListeners.forEach((listener) => {
    try {
      listener()
    } catch {
      // listener errors must not break the request pipeline
    }
  })
}

export class ApiError extends Error {
  status: number
  body: string

  constructor(message: string, status: number, body: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

const networkErrorMessages: Record<'en' | 'es', string> = {
  en: 'Unable to reach the server. Check your connection and try again.',
  es: 'No se pudo conectar con el servidor. Comprueba tu conexión o que la API esté en marcha.',
}

function isLikelyNetworkFailure(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false
  }
  if (error instanceof ApiError) {
    return false
  }
  if (error.name === 'AbortError') {
    return false
  }
  const message = error.message.toLowerCase()
  return (
    message === 'failed to fetch' ||
    message.includes('networkerror') ||
    (error.name === 'TypeError' && message.includes('fetch'))
  )
}

/** User-facing text from a failed API call (`detail` / optional `build_log` when JSON). */
export function formatApiError(
  error: unknown,
  locale: 'en' | 'es' = 'en'
): string {
  if (isLikelyNetworkFailure(error)) {
    return networkErrorMessages[locale]
  }
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : String(error)
  }
  try {
    const parsed = JSON.parse(error.body) as {
      detail?: string
      build_log?: string
    }
    const detail = parsed.detail ?? error.message
    if (parsed.build_log) {
      return `${detail}\n\n${parsed.build_log.slice(-2000)}`
    }
    return detail
  } catch {
    return error.message
  }
}

export interface HealthResponse {
  status: string
}

async function parseJson<T>(response: Response): Promise<T> {
  const text = await response.text()
  if (!text) {
    return undefined as T
  }
  return JSON.parse(text) as T
}

async function readEmptyOk(response: Response): Promise<void> {
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
}

export interface ApiRequestOptions {
  /** Skip attaching the bearer token and the 401 reset (used for /api/auth/login). */
  skipAuth?: boolean
}

function buildHeaders(initHeaders: HeadersInit | undefined, skipAuth: boolean): Headers {
  const headers = new Headers(initHeaders ?? {})
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (!skipAuth) {
    const token = getAccessToken()
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`)
    }
  }
  return headers
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: ApiRequestOptions = {}
): Promise<T> {
  const url = `${getApiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`
  const skipAuth = options.skipAuth === true
  const response = await fetch(url, {
    ...init,
    headers: buildHeaders(init.headers, skipAuth),
  })

  if (!response.ok) {
    const body = await response.text()
    if (response.status === 401 && !skipAuth) {
      clearAccessToken()
      notifyUnauthorized()
    }
    throw new ApiError(
      `Request failed: ${response.status} ${response.statusText}`,
      response.status,
      body
    )
  }

  return parseJson<T>(response)
}

export async function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: 'GET' })
}

/**
 * Send a JSON POST request to the API and return the parsed JSON response.
 *
 * @param path - Path relative to the API base (leading slash optional)
 * @param body - Value to JSON-serialize and send as the request body
 * @param options - Optional request options; when `options.skipAuth` is true the Authorization header is not attached and 401 handling that clears stored tokens is skipped
 * @returns The response body parsed as JSON mapped to `TResponse`
 */
export async function apiPost<TResponse, TBody = unknown>(
  path: string,
  body: TBody,
  options: ApiRequestOptions = {}
): Promise<TResponse> {
  return apiRequest<TResponse>(
    path,
    { method: 'POST', body: JSON.stringify(body) },
    options
  )
}

/**
 * Send a PATCH request with a JSON body to the given API path and return the parsed response.
 *
 * @param path - API path (will be resolved against the configured API base URL)
 * @param body - Payload to serialize as JSON and include in the request body
 * @returns The parsed JSON response as `TResponse`
 */
export async function apiPatch<TResponse, TBody = unknown>(
  path: string,
  body: TBody
): Promise<TResponse> {
  return apiRequest<TResponse>(path, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

/**
 * Send a DELETE request to the API for the given path.
 *
 * Attaches an `Authorization: Bearer <token>` header when an access token is available.
 * On a 401 response the stored access token is cleared and registered unauthorized listeners are notified.
 *
 * @param path - API path relative to the configured API base URL (leading `/` is optional)
 */
export async function apiDelete(path: string): Promise<void> {
  const url = `${getApiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`
  const headers = new Headers({ Accept: 'application/json' })
  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(url, {
    method: 'DELETE',
    headers,
  })
  await readEmptyOk(response)
}

export async function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>('/api/health')
}

// --- Containers (Docker orchestrator) ---

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

export type ProjectRole = 'owner' | 'operator' | 'viewer'

export type RunSourceKind = 'image' | 'git' | 'dockerfile_template'

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
}

export interface RunFromSourceResponse {
  container: ContainerInfo
  kind: RunSourceKind
  image: string
  route_wired: boolean
  public_url?: string | null
}

export interface ImageAvailabilityResponse {
  ref: string
  available: boolean
  checked: boolean
  detail: string | null
  can_attempt_deploy?: boolean
  error_code?: string | null
  hints?: string[] | null
  registry_detail?: string | null
}

export async function getImageAvailability(
  ref: string
): Promise<ImageAvailabilityResponse> {
  const query = new URLSearchParams({ ref })
  return apiGet<ImageAvailabilityResponse>(
    `/api/containers/image/availability?${query.toString()}`
  )
}

export type ImageSuggestionSource = 'local' | 'registry'

export interface ImageSuggestion {
  ref: string
  pull_count: number | null
  source: ImageSuggestionSource
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
): Promise<DeploySourceSuggestion[]> {
  const params = new URLSearchParams({ q: query })
  if (options.limit != null) {
    params.set('limit', String(options.limit))
  }
  const data = await apiGet<{ suggestions: DeploySourceSuggestion[] }>(
    `/api/containers/deploy-sources?${params.toString()}`
  )
  return data.suggestions
}

/**
 * Fetches image suggestions that match the given query.
 *
 * @param query - The search text used to find image suggestions
 * @param options - Optional settings for the request
 * @param options.limit - Maximum number of suggestions to return
 * @returns The list of matching image suggestion objects
 */
export async function getImageSuggestions(
  query: string,
  options: { limit?: number } = {}
): Promise<ImageSuggestion[]> {
  const params = new URLSearchParams({ q: query })
  if (options.limit != null) {
    params.set('limit', String(options.limit))
  }
  const data = await apiGet<{ suggestions: ImageSuggestion[] }>(
    `/api/containers/image/suggestions?${params.toString()}`
  )
  return data.suggestions
}

export async function listContainers(): Promise<ContainerInfo[]> {
  return apiGet<ContainerInfo[]>('/api/containers/')
}

const MAX_CONTAINER_LOG_TAIL = 2000

function apiBaseLooksLikeLocalDevBackend(api: URL): boolean {
  if (api.hostname === 'localhost' || api.hostname === '127.0.0.1') {
    return true
  }
  if (typeof window === 'undefined') {
    return false
  }
  return api.hostname === window.location.hostname
}

/**
 * Build ws/wss URL for the API.
 *
 * HTTPS pages cannot open `ws:` to another port (mixed content). In dev, use the
 * Vite dev server origin + `/api/...` so `vite.config` proxy upgrades WebSockets
 * to FastAPI. In production, if the API base is `http` on the same host as the
 * page, assume a reverse proxy serves `/api` on the page origin and use `wss`
 * there.
 */
export function getApiWebSocketUrl(pathWithQuery: string): string {
  const base = getApiBaseUrl()
  const path = pathWithQuery.startsWith('/') ? pathWithQuery : `/${pathWithQuery}`

  if (typeof window !== 'undefined' && import.meta.env.DEV) {
    try {
      const api = new URL(base)
      if (apiBaseLooksLikeLocalDevBackend(api)) {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        return `${wsProtocol}//${window.location.host}${path}`
      }
    } catch {
      // fall through
    }
  }

  if (typeof window !== 'undefined' && window.location.protocol === 'https:') {
    try {
      const api = new URL(base)
      if (api.protocol === 'http:' && api.hostname === window.location.hostname) {
        return `wss://${window.location.host}${path}`
      }
    } catch {
      // fall through
    }
  }

  if (base.startsWith('https://')) {
    return `wss://${base.slice('https://'.length)}${path}`
  }
  return `ws://${base.slice('http://'.length)}${path}`
}

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

export type AiPrefillPreferences = {
  git_branch: boolean
  container_port: boolean
  container_name: boolean
  env_vars: boolean
  start_command: boolean
}

export type AiPrefillPreferencesUpdate = Partial<AiPrefillPreferences>

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

export async function getAiPrefillPreferences(): Promise<AiPrefillPreferences> {
  return apiGet<AiPrefillPreferences>('/api/settings/ai-prefill')
}

export async function patchAiPrefillPreferences(
  patch: AiPrefillPreferencesUpdate
): Promise<AiPrefillPreferences> {
  return apiPatch<AiPrefillPreferences, AiPrefillPreferencesUpdate>(
    '/api/settings/ai-prefill',
    patch
  )
}

export async function getGeminiConfigStatus(): Promise<{ configured: boolean }> {
  return apiGet<{ configured: boolean }>('/api/settings/gemini-status')
}

// --- Email Notifications ---

export type EmailNotificationPreferences = {
  id: string | null
  user_id: string
  email: string
  alerts_enabled: boolean
  alert_types: Array<'stop' | 'failure' | 'unhealthy'>
  alert_frequency: 'immediate' | 'daily_digest' | 'weekly_summary'
  created_at: string
  updated_at: string
}

export type EmailNotificationPreferencesUpdate = Partial<Omit<EmailNotificationPreferences, 'id' | 'user_id' | 'created_at' | 'updated_at'>>

export type AlertHistoryEntry = {
  id: string
  container_id: string
  event_type: string
  sent_at: string
  email_sent_to: string | null
  status: 'sent' | 'failed'
}

export async function getEmailNotificationPreferences(): Promise<EmailNotificationPreferences> {
  return apiGet<EmailNotificationPreferences>('/api/settings/email-notifications')
}

export async function updateEmailNotificationPreferences(
  patch: EmailNotificationPreferencesUpdate
): Promise<EmailNotificationPreferences> {
  return apiPatch<EmailNotificationPreferences, EmailNotificationPreferencesUpdate>(
    '/api/settings/email-notifications',
    patch
  )
}

export async function getAlertHistory(options: {
  limit?: number
  container_id?: string
} = {}): Promise<AlertHistoryEntry[]> {
  const params = new URLSearchParams()
  if (options.limit != null) {
    params.set('limit', String(options.limit))
  }
  if (options.container_id) {
    params.set('container_id', options.container_id)
  }
  const query = params.toString()
  return apiGet<AlertHistoryEntry[]>(
    query ? `/api/settings/email-notifications/history?${query}` : '/api/settings/email-notifications/history'
  )
}

// --- Team / projects ---

export type Project = {
  id: string
  name: string
  is_personal: boolean
  role: ProjectRole
  owner_email: string
}

export type ProjectMember = {
  user_id: string
  email: string
  role: ProjectRole
  created_at: string
}

export type ProjectInvitation = {
  id: string
  invitee_user_id: string
  email: string
  role: 'operator' | 'viewer'
  created_at: string
}

export type IncomingProjectInvitation = {
  id: string
  project_id: string
  project_name: string
  inviter_email: string
  role: 'operator' | 'viewer'
  created_at: string
}

export async function listProjects(): Promise<Project[]> {
  return apiGet<Project[]>('/api/projects/')
}

export async function createProject(name: string): Promise<Project> {
  return apiPost<Project, { name: string }>('/api/projects/', { name })
}

export async function apiPostEmpty(path: string): Promise<void> {
  const url = `${getApiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`
  const headers = new Headers({ Accept: 'application/json', 'Content-Type': 'application/json' })
  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(url, { method: 'POST', headers, body: '{}' })
  await readEmptyOk(response)
}

export async function leaveProject(projectId: string): Promise<void> {
  await apiPostEmpty(
    `/api/projects/${encodeURIComponent(projectId)}/leave`,
  )
}

export async function listProjectMembers(projectId: string): Promise<ProjectMember[]> {
  return apiGet<ProjectMember[]>(`/api/projects/${encodeURIComponent(projectId)}/members`)
}

export async function listProjectInvitations(projectId: string): Promise<ProjectInvitation[]> {
  return apiGet<ProjectInvitation[]>(
    `/api/projects/${encodeURIComponent(projectId)}/invitations`
  )
}

export async function createProjectInvitation(
  projectId: string,
  body: { email: string; role: 'operator' | 'viewer' }
): Promise<ProjectInvitation> {
  return apiPost<ProjectInvitation, { email: string; role: 'operator' | 'viewer' }>(
    `/api/projects/${encodeURIComponent(projectId)}/invitations`,
    body
  )
}

export async function cancelProjectInvitation(
  projectId: string,
  invitationId: string
): Promise<void> {
  await apiDelete(
    `/api/projects/${encodeURIComponent(projectId)}/invitations/${encodeURIComponent(invitationId)}`
  )
}

export async function listIncomingInvitations(): Promise<IncomingProjectInvitation[]> {
  return apiGet<IncomingProjectInvitation[]>('/api/projects/invitations/incoming')
}

export async function acceptProjectInvitation(invitationId: string): Promise<Project> {
  return apiPost<Project>(
    `/api/projects/invitations/${encodeURIComponent(invitationId)}/accept`,
    {}
  )
}

export async function rejectProjectInvitation(invitationId: string): Promise<void> {
  await apiPostEmpty(
    `/api/projects/invitations/${encodeURIComponent(invitationId)}/reject`,
  )
}

export async function updateProjectMemberRole(
  projectId: string,
  userId: string,
  role: 'operator' | 'viewer'
): Promise<ProjectMember> {
  return apiPatch<ProjectMember, { role: 'operator' | 'viewer' }>(
    `/api/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`,
    { role }
  )
}

export async function removeProjectMember(
  projectId: string,
  userId: string
): Promise<void> {
  await apiDelete(
    `/api/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`
  )
}

export function containerWriteAllowed(container: ContainerInfo): boolean {
  return container.access_role === 'owner' || container.access_role === 'operator'
}

export async function analyzeGitSource(body: {
  git_url: string
  git_branch: string
}): Promise<GitSourceAnalysis> {
  return apiPost<GitSourceAnalysis, typeof body>(
    '/api/builder/analyze-source',
    body
  )
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

// --- Auth ---

export interface UserPublic {
  id: string
  email: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  user: UserPublic
}

export interface RegisterRequest {
  email: string
  password: string
}

export interface LoginRequest {
  email: string
  password: string
}

export async function registerUser(
  body: RegisterRequest
): Promise<TokenResponse> {
  return apiPost<TokenResponse, RegisterRequest>(
    '/api/auth/register',
    body,
    { skipAuth: true }
  )
}

export async function login(body: LoginRequest): Promise<TokenResponse> {
  return apiPost<TokenResponse, LoginRequest>('/api/auth/login', body, {
    skipAuth: true,
  })
}

export async function getMe(): Promise<UserPublic> {
  return apiGet<UserPublic>('/api/auth/me')
}

// --- GitHub OAuth ---

export interface GithubStatus {
  connected: boolean
  login: string | null
  avatar_url: string | null
  scopes: string[]
  connected_at: string | null
}

export interface GithubAuthorizeUrlResponse {
  authorize_url: string
}

export interface GithubRepo {
  full_name: string
  default_branch: string
  private: boolean
  html_url: string
  description: string | null
}

export interface GithubBranch {
  name: string
}

export async function getGithubStatus(): Promise<GithubStatus> {
  return apiGet<GithubStatus>('/api/auth/github/status')
}

const disconnectedGithubStatus: GithubStatus = {
  connected: false,
  login: null,
  avatar_url: null,
  scopes: [],
  connected_at: null,
}

/** Same as getGithubStatus but tolerates a cold API or brief network failures (e.g. right after dev server start). */
export async function getGithubStatusWithRetry(): Promise<GithubStatus> {
  const backoffMs = [0, 400, 1200]
  let lastError: unknown
  for (const wait of backoffMs) {
    if (wait > 0) {
      await new Promise((resolve) => setTimeout(resolve, wait))
    }
    if (!getAccessToken()) {
      return disconnectedGithubStatus
    }
    try {
      return await getGithubStatus()
    } catch (error) {
      lastError = error
    }
  }
  if (lastError !== undefined) {
    throw lastError
  }
  return disconnectedGithubStatus
}

export async function getGithubAuthorizeUrl(): Promise<GithubAuthorizeUrlResponse> {
  return apiGet<GithubAuthorizeUrlResponse>('/api/auth/github/start')
}

export async function disconnectGithub(): Promise<void> {
  await apiDelete('/api/auth/github')
}

export interface ListGithubReposParams {
  /** Server-side filter (GitHub search API). Prefer client-side filtering after fetchAllGithubRepos when browsing. */
  query?: string
  page?: number
  perPage?: number
}

export async function listGithubRepos(
  params?: ListGithubReposParams
): Promise<GithubRepo[]> {
  const page = params?.page ?? 1
  const perPage = Math.min(100, Math.max(1, params?.perPage ?? 30))
  const searchParams = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  })
  const trimmedQuery = params?.query?.trim()
  if (trimmedQuery) {
    searchParams.set('q', trimmedQuery)
  }
  return apiGet<GithubRepo[]>(`/api/github/repos?${searchParams.toString()}`)
}

const GITHUB_REPOS_FULL_FETCH_PAGE_SIZE = 100
const GITHUB_REPOS_FULL_FETCH_MAX_PAGES = 100

/** Load every repo page from ``GET /api/github/repos`` (no search query) for client-side filtering. */
export async function fetchAllGithubRepos(): Promise<GithubRepo[]> {
  const all: GithubRepo[] = []
  const seen = new Set<string>()
  for (let page = 1; page <= GITHUB_REPOS_FULL_FETCH_MAX_PAGES; page++) {
    const batch = await listGithubRepos({
      page,
      perPage: GITHUB_REPOS_FULL_FETCH_PAGE_SIZE,
    })
    for (const repo of batch) {
      if (repo.full_name && !seen.has(repo.full_name)) {
        seen.add(repo.full_name)
        all.push(repo)
      }
    }
    if (batch.length < GITHUB_REPOS_FULL_FETCH_PAGE_SIZE) {
      break
    }
  }
  return all
}

/**
 * Filter a list of GitHub repositories by a search query.
 *
 * The function trims `query` and, if non-empty, attempts a case-insensitive
 * `RegExp` match against each repo's `full_name` and `description`. If the
 * regex is invalid, it falls back to a case-insensitive substring search.
 * An empty or whitespace-only `query` returns the original `repos` array.
 *
 * @param repos - Array of repositories to filter
 * @param query - Search string or regular-expression pattern
 * @returns The repositories whose `full_name` or `description` match `query`
 */
export function filterGithubReposByQuery(
  repos: GithubRepo[],
  query: string
): GithubRepo[] {
  const trimmed = query.trim()
  if (!trimmed) {
    return repos
  }
  try {
    const pattern = new RegExp(trimmed, 'i')
    return repos.filter(
      (repo) =>
        pattern.test(repo.full_name) ||
        (repo.description !== null &&
          repo.description !== undefined &&
          pattern.test(repo.description))
    )
  } catch {
    const needle = trimmed.toLowerCase()
    return repos.filter(
      (repo) =>
        repo.full_name.toLowerCase().includes(needle) ||
        (repo.description?.toLowerCase().includes(needle) ?? false)
    )
  }
}

// --- User library (Dockerfile templates) ---

export interface DockerfileTemplate {
  id: string
  name: string
  contents: string
  created_at: string
  updated_at: string
}

/**
 * Retrieves all Dockerfile templates in the user's library.
 *
 * @returns An array of `DockerfileTemplate` objects
 */
export async function listDockerfileTemplates(): Promise<DockerfileTemplate[]> {
  return apiGet<DockerfileTemplate[]>('/api/dockerfiles/')
}

/**
 * Create a new Dockerfile template.
 *
 * @param body - The template payload containing `name` and `contents`
 * @returns The created `DockerfileTemplate`
 */
export async function createDockerfileTemplate(body: {
  name: string
  contents: string
}): Promise<DockerfileTemplate> {
  return apiPost<DockerfileTemplate, { name: string; contents: string }>(
    '/api/dockerfiles/',
    body
  )
}

/**
 * Update an existing Dockerfile template.
 *
 * @param templateId - The identifier of the Dockerfile template to update
 * @param body - Partial template fields to change; may include `name` and/or `contents`
 * @returns The updated DockerfileTemplate
 */
export async function updateDockerfileTemplate(
  templateId: string,
  body: { name?: string; contents?: string }
): Promise<DockerfileTemplate> {
  return apiPatch<DockerfileTemplate, { name?: string; contents?: string }>(
    `/api/dockerfiles/${encodeURIComponent(templateId)}`,
    body
  )
}

/**
 * Delete a Dockerfile template by its identifier.
 *
 * @param templateId - The ID of the Dockerfile template to remove
 */
export async function deleteDockerfileTemplate(templateId: string): Promise<void> {
  await apiDelete(`/api/dockerfiles/${encodeURIComponent(templateId)}`)
}

/**
 * Fetches the branches for a GitHub repository identified by its full name.
 *
 * @param fullName - The repository full name in the form `owner/repo`
 * @returns The list of repository branches
 * @throws Error when `fullName` is not in the `owner/repo` format
 */
export async function listGithubRepoBranches(
  fullName: string
): Promise<GithubBranch[]> {
  const slashIndex = fullName.indexOf('/')
  if (slashIndex <= 0 || slashIndex === fullName.length - 1) {
    throw new Error(`Invalid repo full_name: ${fullName}`)
  }
  const owner = encodeURIComponent(fullName.slice(0, slashIndex))
  const repo = encodeURIComponent(fullName.slice(slashIndex + 1))
  return apiGet<GithubBranch[]>(`/api/github/repos/${owner}/${repo}/branches`)
}
