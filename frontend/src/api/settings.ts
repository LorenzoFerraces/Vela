import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './core'

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

export type LlmProviderKind = 'openai_compatible' | 'gemini' | 'anthropic'

export type LlmProviderConfig = {
  provider: LlmProviderKind
  base_url: string | null
  model: string
  has_key: boolean
}

export type LlmProviderUpdate = {
  provider: LlmProviderKind
  base_url?: string | null
  model: string
  api_key?: string | null
}

export type LlmProviderTestRequest = {
  provider: LlmProviderKind
  base_url?: string | null
  model: string
  api_key: string
}

export type LlmProviderTestResult = {
  ok: boolean
  models: string[] | null
}

export type GeminiConfigStatus = {
  configured: boolean
  user_provider: LlmProviderConfig | null
}

export async function getGeminiConfigStatus(): Promise<GeminiConfigStatus> {
  return apiGet<GeminiConfigStatus>('/api/settings/gemini-status')
}

export async function getLlmProvider(): Promise<LlmProviderConfig | null> {
  return apiGet<LlmProviderConfig | null>('/api/settings/llm-provider')
}

export async function putLlmProvider(
  update: LlmProviderUpdate
): Promise<LlmProviderConfig> {
  return apiPut<LlmProviderConfig, LlmProviderUpdate>(
    '/api/settings/llm-provider',
    update
  )
}

export async function deleteLlmProvider(): Promise<void> {
  await apiDelete('/api/settings/llm-provider')
}

export async function testLlmProvider(
  request: LlmProviderTestRequest
): Promise<LlmProviderTestResult> {
  return apiPost<LlmProviderTestResult, LlmProviderTestRequest>(
    '/api/settings/llm-provider/test',
    request
  )
}
