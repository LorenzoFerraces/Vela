import { apiDelete, apiGet } from './core'

export interface PreviewPublic {
  id: string
  repo_full_name: string
  pr_number: number
  head_sha: string
  public_url: string | null
  route_host: string | null
  expires_at: string
  status: string
  closed_at: string | null
}

export const listPreviews = (projectId: string) =>
  apiGet<PreviewPublic[]>(`/api/projects/${projectId}/previews`)

export const revokePreview = (projectId: string, previewId: string) =>
  apiDelete(`/api/projects/${projectId}/previews/${previewId}`)
