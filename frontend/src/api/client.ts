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
}

export interface RunFromSourceRequest {
  source: string
  container_name?: string | null
  host_port?: number | null
  container_port?: number
  git_branch?: string
  route_host?: string | null
  route_path_prefix?: string
  route_tls?: boolean
  public_route?: boolean
}

export interface RunFromSourceResponse {
  container: ContainerInfo
  kind: 'image' | 'git'
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

export async function getGithubAuthorizeUrl(): Promise<GithubAuthorizeUrlResponse> {
  return apiGet<GithubAuthorizeUrlResponse>('/api/auth/github/start')
}

export async function disconnectGithub(): Promise<void> {
  await apiDelete('/api/auth/github')
}

export async function listGithubRepos(
  query?: string,
  page: number = 1
): Promise<GithubRepo[]> {
  const params = new URLSearchParams({ page: String(page) })
  const trimmedQuery = query?.trim()
  if (trimmedQuery) {
    params.set('q', trimmedQuery)
  }
  return apiGet<GithubRepo[]>(`/api/github/repos?${params.toString()}`)
}

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
