import { ApiError } from './core'

/**
 * True when the API reports a user-provider LLM failure while the server's
 * own provider is still usable as a one-click fallback.
 */
export function isLlmFallbackError(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return false
  }
  try {
    const parsed = JSON.parse(error.body) as { fallback_available?: unknown }
    return parsed.fallback_available === true
  } catch {
    return false
  }
}
