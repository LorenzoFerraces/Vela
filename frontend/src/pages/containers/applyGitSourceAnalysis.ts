import type { AiPrefillPreferences, GitSourceAnalysis } from '../../api/client'
import {
  envRowsFromRecord,
  formatStartCommand,
  type EnvVarRow,
} from './runFormAdvanced'

export type GitAnalysisFormSetters = {
  setGitBranch: (value: string) => void
  setContainerPort: (value: string) => void
  setContainerName: (value: string) => void
  setEnvRows: (rows: EnvVarRow[]) => void
  setStartCommand: (value: string) => void
}

export function applyGitSourceAnalysis(
  analysis: GitSourceAnalysis,
  preferences: AiPrefillPreferences,
  setters: GitAnalysisFormSetters
): void {
  if (preferences.git_branch && analysis.git_branch) {
    setters.setGitBranch(analysis.git_branch)
  }
  if (preferences.container_port) {
    setters.setContainerPort(String(analysis.container_port))
  }
  if (preferences.container_name && analysis.container_name) {
    setters.setContainerName(analysis.container_name)
  }
  if (preferences.env_vars && Object.keys(analysis.env_vars).length > 0) {
    setters.setEnvRows(envRowsFromRecord(analysis.env_vars))
  }
  if (preferences.start_command && analysis.start_command?.length) {
    setters.setStartCommand(formatStartCommand(analysis.start_command))
  }
}
