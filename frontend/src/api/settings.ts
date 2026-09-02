import { apiGet, apiPatch } from './core'

export type AiPrefillPreferences = {
  git_branch: boolean
  container_port: boolean
  container_name: boolean
  env_vars: boolean
  start_command: boolean
}

export type AiPrefillPreferencesUpdate = Partial<AiPrefillPreferences>

export async function getAiPrefillPreferences(): Promise<AiPrefillPreferences> {
  return apiGet<AiPrefillPreferences>('/api/settings/ai-prefill')
}

export async function patchAiPrefillPreferences(
  patch: AiPrefillPreferencesUpdate
): Promise<AiPrefillPreferences> {
  return apiPatch<AiPrefillPreferences, AiPrefillPreferencesUpdate>(
    '/api/settings/ai-prefill',
    patch
  )
}

export async function getGeminiConfigStatus(): Promise<{ configured: boolean }> {
  return apiGet<{ configured: boolean }>('/api/settings/gemini-status')
}
