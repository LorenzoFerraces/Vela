import { useState } from 'react'
import { sourceLooksLikeGitUrl } from './sourceKind'

export function useRunFormSource() {
  const [source, setSource] = useState('')
  const [containerPort, setContainerPort] = useState('80')
  const showGitBranch = sourceLooksLikeGitUrl(source)

  function updateSourceInput(nextRaw: string) {
    const previousKindWasGit = sourceLooksLikeGitUrl(source)
    const nextKindIsGit = sourceLooksLikeGitUrl(nextRaw)
    setSource(nextRaw)
    if (previousKindWasGit === nextKindIsGit) {
      return
    }
    setContainerPort((portString) => {
      if (nextKindIsGit) {
        return portString === '80' ? '5173' : portString
      }
      return portString === '5173' ? '80' : portString
    })
  }

  return {
    source,
    containerPort,
    setContainerPort,
    showGitBranch,
    updateSourceInput,
  }
}
