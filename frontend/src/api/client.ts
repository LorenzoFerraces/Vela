/**
 * Thin HTTP client for the Vela FastAPI backend.
 * Base URL: `VITE_API_BASE_URL` or http://localhost:8000
 */

const defaultBaseUrl = 'http://localhost:8000'

export function getApiBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_API_BASE_URL
  return typeof fromEnv === 'string' && fromEnv.length > 0
    ? fromEnv.replace(/\/$/, '')
    : defaultBaseUrl
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

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const url = `${getApiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...init.headers,
    },
  })

  if (!response.ok) {
    const body = await response.text()
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
  body: TBody
): Promise<TResponse> {
  return apiRequest<TResponse>(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>('/api/health')
}
