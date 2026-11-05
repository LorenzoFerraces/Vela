import { useCallback, useEffect, useState } from 'react'
import {
  analyzeGitSource,
  formatApiError,
  getAiPrefillPreferences,
  isLlmFallbackError,
  type AiPrefillPreferences,
  type GitSourceAnalysis,
} from '../../api/client'
import { applyGitSourceAnalysis, type GitAnalysisFormSetters } from './applyGitSourceAnalysis'

const DEFAULT_AI_PREFILL_PREFERENCES: AiPrefillPreferences = {
  git_branch: true,
  container_port: true,
  container_name: true,
  env_vars: true,
  start_command: true,
}

export function useGitSourceAnalysis(setters: GitAnalysisFormSetters) {
  const [preferences, setPreferences] = useState<AiPrefillPreferences | null>(
    null
  )
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [llmFallbackAvailable, setLlmFallbackAvailable] = useState(false)
  const [successToast, setSuccessToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void getAiPrefillPreferences()
      .then((prefs) => {
        if (!cancelled) {
          setPreferences(prefs)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPreferences(DEFAULT_AI_PREFILL_PREFERENCES)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const clearAnalysis = useCallback(() => {
    setAnalysisLoading(false)
    setAnalysisError(null)
    setLlmFallbackAvailable(false)
    setSuccessToast(null)
  }, [])

  const dismissSuccessToast = useCallback(() => {
    setSuccessToast(null)
  }, [])

  const runAnalysis = useCallback(
    async (
      gitUrl: string,
      gitBranch: string,
      useServerDefault = false,
    ): Promise<GitSourceAnalysis | null> => {
      setAnalysisLoading(true)
      setAnalysisError(null)
      setLlmFallbackAvailable(false)
      setSuccessToast(null)
      try {
        let prefs = preferences
        if (!prefs) {
          try {
            prefs = await getAiPrefillPreferences()
          } catch (loadError) {
            console.debug('AI prefill preferences unavailable:', loadError)
            prefs = DEFAULT_AI_PREFILL_PREFERENCES
          }
        }
        const analysis: GitSourceAnalysis = await analyzeGitSource({
          git_url: gitUrl,
          git_branch: gitBranch,
          use_server_default: useServerDefault,
        })
        applyGitSourceAnalysis(analysis, prefs, setters)
        const hint = analysis.summary_hint?.trim()
        setSuccessToast(
          hint || 'Repository analyzed. Deploy settings updated.'
        )
        return analysis
      } catch (error) {
        setLlmFallbackAvailable(isLlmFallbackError(error))
        setAnalysisError(formatApiError(error))
        return null
      } finally {
        setAnalysisLoading(false)
      }
    },
    [preferences, setters]
  )

  return {
    analysisLoading,
    analysisError,
    llmFallbackAvailable,
    successToast,
    dismissSuccessToast,
    runAnalysis,
    clearAnalysis,
  }
}
