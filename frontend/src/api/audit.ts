import { apiGet } from './core'

export type AuditLogEntry = {
  id: string
  user_id: string
  action: string
  target_type: string
  target_id: string
  details: Record<string, unknown> | null
  created_at: string
}

export type AuditLogResponse = {
  entries: AuditLogEntry[]
  total: number
}

export type AuditLogQueryParams = {
  action?: string
  target_type?: string
  from_date?: string
  to_date?: string
  limit?: number
  offset?: number
}

export async function getAuditLog(
  params: AuditLogQueryParams = {}
): Promise<AuditLogResponse> {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.set(key, String(value))
    }
  }
  const query = searchParams.toString()
  return apiGet<AuditLogResponse>(
    query ? `/api/audit/log?${query}` : '/api/audit/log'
  )
}
