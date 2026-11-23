import {
  apiGet,
  endSessionForAuthError,
  getAccessToken,
  getApiBaseUrl,
} from './core'

export interface TeamShowback {
  team_name: string
  cpu_seconds: number
  memory_gib_hours: number
  storage_gib_days: number
  cost_currency: null
}

export interface ShowbackSummary {
  month: string
  teams: TeamShowback[]
}

export const getShowback = (): Promise<ShowbackSummary> =>
  apiGet<ShowbackSummary>('/api/metrics/showback')

export async function exportShowbackCsv(month: string): Promise<void> {
  const url = `${getApiBaseUrl()}/api/metrics/showback/export?month=${encodeURIComponent(month)}`
  const headers = new Headers({ Accept: 'text/csv' })
  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(url, { headers })
  if (!response.ok) {
    endSessionForAuthError(response, await response.text())
    throw new Error('Could not export showback report')
  }
  const blob = await response.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `vela-showback-${month}.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}
