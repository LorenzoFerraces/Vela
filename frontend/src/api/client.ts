/**
 * Thin HTTP client for the Vela FastAPI backend.
 * Base URL: `VITE_API_BASE_URL` or `window.location.hostname:8000`
 */

// --- Request deduplication and caching ---
const activeRequests = new Map<string, Promise<unknown>>()
const cache = new Map<string, { data: unknown; timestamp: number }>()
const CACHE_TTL = 5 * 60 * 1000 // 5 minutes cache TTL

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
  /** Enable caching for this request (default false). */
  cache?: boolean
  /** Cache TTL in milliseconds (default 5 minutes). */
  cacheTtl?: number
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
  const shouldCache = options.cache === true
  
  // Request deduplication
  const cacheKey = `${url}-${JSON.stringify(init)}`
  if (activeRequests.has(cacheKey)) {
    return activeRequests.get(cacheKey) as Promise<T>
  }

  // Check cache first if enabled
  if (shouldCache) {
    const cached = cache.get(cacheKey)
    if (cached && Date.now() - cached.timestamp < (options.cacheTtl || CACHE_TTL)) {
      return cached.data as T
    }
  }

  const requestPromise = fetch(url, {
    ...init,
    headers: buildHeaders(init.headers, skipAuth),
  }).then(async (response) => {
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

    const data = await parseJson<T>(response)
    
    // Cache result if enabled
    if (shouldCache) {
      cache.set(cacheKey, { data, timestamp: Date.now() })
    }
    
    return data
  })

  // Track active request for deduplication
  activeRequests.set(cacheKey, requestPromise)
  requestPromise.finally(() => activeRequests.delete(cacheKey))
  
  return requestPromise
}

export async function apiGet<T>(path: string, options?: ApiRequestOptions): Promise<T> {
  return apiRequest<T>(path, { method: 'GET' }, options)
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

export async function apiUploadFile<T>(
  path: string,
  formData: FormData
): Promise<T> {
  const url = `${getApiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`
  const headers = new Headers({ Accept: 'application/json' })
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

  return parseJson<T>(response)
}

export async function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>('/api/health')
}