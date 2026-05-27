import { useCallback, useEffect, useState } from 'react'
import {
  analyzeGitSource,
  formatApiError,
  getAiPrefillPreferences,
  type AiPrefillPreferences,
  type GitSourceAnalysis,
} from '../../api/client'
import { applyGitSourceAnalysis, type GitAnalysisFormSetters } from './applyGitSourceAnalysis'

export function useGitSourceAnalysis(setters: GitAnalysisFormSetters) {
  const [preferences, setPreferences] = useState<AiPrefillPreferences | null>(
    null
  )
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)

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
          setPreferences({
            git_branch: true,
            container_port: true,
            container_name: true,
            env_vars: true,
            start_command: true,
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const clearAnalysis = useCallback(() => {
    setAnalysisLoading(false)
    setAnalysisError(null)
  }, [])

  const runAnalysis = useCallback(
    async (gitUrl: string, gitBranch: string) => {
      setAnalysisLoading(true)
      setAnalysisError(null)
      try {
        const prefs =
          preferences ??
          (await getAiPrefillPreferences())
        const analysis: GitSourceAnalysis = await analyzeGitSource({
          git_url: gitUrl,
          git_branch: gitBranch,
        })
        applyGitSourceAnalysis(analysis, prefs, setters)
      } catch (error) {
        setAnalysisError(formatApiError(error))
      } finally {
        setAnalysisLoading(false)
      }
    },
    [preferences, setters]
  )

  return {
    analysisLoading,
    analysisError,
    runAnalysis,
    clearAnalysis,
  }
}
