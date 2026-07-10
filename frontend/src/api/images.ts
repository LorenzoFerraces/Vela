/**
 * Image and Dockerfile API endpoints for the Vela application.
 */
import { apiDelete, apiGet, apiPatch, apiPost } from '../client'
import { ImageAvailabilityResponse, ImageSuggestion, ImageSuggestionSource, DeploySourceSuggestion } from './types'

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

export async function getImageAvailability(
  ref: string
): Promise<ImageAvailabilityResponse> {
  const query = new URLSearchParams({ ref })
  return apiGet<ImageAvailabilityResponse>(
    `/api/containers/image/availability?${query.toString()}`
  )
}

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

// --- User library (saved image references) ---

export interface SavedImage {
  id: string
  ref: string
  created_at: string
}

export async function listSavedImages(): Promise<SavedImage[]> {
  return apiGet<SavedImage[]>('/api/saved-images/')
}

export async function createSavedImage(ref: string): Promise<SavedImage> {
  return apiPost<SavedImage, { ref: string }>('/api/saved-images/', { ref })
}

export async function updateSavedImage(
  imageId: string,
  ref: string
): Promise<SavedImage> {
  return apiPatch<SavedImage, { ref: string }>(
    `/api/saved-images/${encodeURIComponent(imageId)}`,
    { ref }
  )
}

export async function deleteSavedImage(imageId: string): Promise<void> {
  await apiDelete(`/api/saved-images/${encodeURIComponent(imageId)}`)
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

export async function getDockerfileTemplate(
  templateId: string
): Promise<DockerfileTemplate> {
  return apiGet<DockerfileTemplate>(`/api/dockerfiles/${encodeURIComponent(templateId)}`)
}

export async function getSavedImage(
  imageId: string
): Promise<SavedImage> {
  return apiGet<SavedImage>(`/api/saved-images/${encodeURIComponent(imageId)}`)
}