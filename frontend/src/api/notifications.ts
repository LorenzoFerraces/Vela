import { apiGet, apiPatch } from './core'

export type EmailNotificationPreferences = {
  id: string | null
  user_id: string
  email: string
  alerts_enabled: boolean
  alert_types: Array<'stop' | 'failure' | 'unhealthy' | 'storage'>
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
