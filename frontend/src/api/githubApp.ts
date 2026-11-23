import { apiGet, apiPut } from './core'

export interface GitHubAppConfigPublic {
  configured: boolean
  app_id: string | null
  slug: string | null
  has_private_key: boolean
  has_webhook_secret: boolean
  connected_at: string | null
}

export interface WebhookConfigPublic {
  project_id: string
  repo_full_name: string | null
  enabled: boolean
  branch_filters: string[]
  preview_enabled: boolean
  preview_ttl_seconds: number
}

export interface WebhookDeliveryPublic {
  delivery_id: string
  event: string
  action: string | null
  branch: string | null
  status: string
  received_at: string
  error: string | null
}

export interface GitHubAppConfigUpdate {
  app_id: string
  slug?: string
  private_key: string
  webhook_secret: string
}

export interface WebhookConfigUpdate {
  repo_full_name: string
  enabled: boolean
  branch_filters: string[]
  preview_enabled: boolean
  preview_ttl_seconds: number
}

export const getGithubAppConfig = () =>
  apiGet<GitHubAppConfigPublic>('/api/settings/github-app')

export const setGithubAppConfig = (body: GitHubAppConfigUpdate) =>
  apiPut<GitHubAppConfigPublic, GitHubAppConfigUpdate>(
    '/api/settings/github-app',
    body,
  )

export const getWebhookConfig = (projectId: string) =>
  apiGet<WebhookConfigPublic>(`/api/projects/${projectId}/github-webhook`)

export const setWebhookConfig = (
  projectId: string,
  body: WebhookConfigUpdate,
) =>
  apiPut<WebhookConfigPublic, WebhookConfigUpdate>(
    `/api/projects/${projectId}/github-webhook`,
    body,
  )

export const listWebhookDeliveries = (projectId: string) =>
  apiGet<WebhookDeliveryPublic[]>(
    `/api/projects/${projectId}/github-webhook/deliveries`,
  )
