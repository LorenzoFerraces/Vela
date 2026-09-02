import { ApiError, apiGet, getAccessToken, getApiBaseUrl } from './core'

export type LogEntry = {
  container_id: string
  container_name: string | null
  timestamp: string
  source: 'stdout' | 'stderr'
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
}

export type LogQueryResponse = {
  entries: LogEntry[]
  total: number
}

export type LogQueryParams = {
  container_id?: string
  level?: string
  source?: string
  start_time?: string
  end_time?: string
  q?: string
  limit?: number
  offset?: number
}

export async function getLogs(
  params: LogQueryParams = {}
): Promise<LogQueryResponse> {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.set(key, String(value))
    }
  }
  const query = searchParams.toString()
  return apiGet<LogQueryResponse>(
    query ? `/api/logs/?${query}` : '/api/logs/'
  )
}

export async function exportLogs(params: Partial<LogQueryParams> = {}) {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.set(key, String(value))
    }
  }
  const url = `${getApiBaseUrl()}/api/logs/export?${searchParams.toString()}`
  const headers = new Headers({ Accept: 'text/csv' })
  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(url, { headers })
  if (!response.ok) {
    throw new ApiError(
      `Export failed: ${response.status} ${response.statusText}`,
      response.status,
      await response.text()
    )
  }
  const blob = await response.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = 'container-logs.csv'
  link.click()
  URL.revokeObjectURL(link.href)
}
