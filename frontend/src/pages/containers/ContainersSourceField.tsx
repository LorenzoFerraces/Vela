import { useEffect, useId, useState } from 'react'
import { getImageSuggestions } from '../../api/client'
import type { ImageRefCheckState } from './types'
import { sourceLooksLikeGitUrl } from './sourceKind'

const IMAGE_SUGGEST_DEBOUNCE_MS = 320
const IMAGE_SUGGEST_LIMIT = 22

type ContainersSourceFieldProps = {
  source: string
  showGitBranch: boolean
  imageRefCheck: ImageRefCheckState
  onSourceChange: (nextRaw: string) => void
  onRequestImageCheck: (trimmedRef: string) => void
}

export function ContainersSourceField({
  source,
  showGitBranch,
  imageRefCheck,
  onSourceChange,
  onRequestImageCheck,
}: ContainersSourceFieldProps) {
  const suggestionsListId = useId()
  const [suggestionRefs, setSuggestionRefs] = useState<string[]>([])
  const trimmedSource = source.trim()
  const imageSuggestionsEnabled =
    !showGitBranch &&
    (trimmedSource.length === 0 || !sourceLooksLikeGitUrl(trimmedSource))

  useEffect(() => {
    if (!imageSuggestionsEnabled) {
      return
    }
    const timer = window.setTimeout(() => {
      void getImageSuggestions(trimmedSource, { limit: IMAGE_SUGGEST_LIMIT })
        .then((rows) => {
          setSuggestionRefs(rows.map((row) => row.ref))
        })
        .catch(() => {
          setSuggestionRefs([])
        })
    }, IMAGE_SUGGEST_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [trimmedSource, imageSuggestionsEnabled])

  return (
    <>
      <input
        id="source-input"
        className="containers-form__input"
        type="text"
        autoComplete="off"
        list={imageSuggestionsEnabled ? suggestionsListId : undefined}
        placeholder="nginx:alpine or https://github.com/org/repo.git"
        value={source}
        onChange={(e) => onSourceChange(e.target.value)}
        onBlur={() => {
          const trimmed = source.trim()
          if (trimmed && !sourceLooksLikeGitUrl(trimmed)) {
            void onRequestImageCheck(trimmed)
          }
        }}
        aria-label="Docker image reference or Git clone URL"
        aria-invalid={
          !showGitBranch &&
          imageRefCheck.status === 'unavailable' &&
          !imageRefCheck.canAttemptDeploy
            ? true
            : undefined
        }
        aria-describedby={
          !showGitBranch && imageRefCheck.status !== 'idle'
            ? 'source-input-status'
            : undefined
        }
      />
      {imageSuggestionsEnabled ? (
        <datalist id={suggestionsListId}>
          {suggestionRefs.map((refValue) => (
            <option key={refValue} value={refValue} />
          ))}
        </datalist>
      ) : null}
      {!showGitBranch && imageRefCheck.status === 'checking' ? (
        <p
          id="source-input-status"
          className="containers-source-check containers-source-check--muted"
        >
          Checking registry…
        </p>
      ) : null}
      {!showGitBranch && imageRefCheck.status === 'ok' ? (
        <p
          id="source-input-status"
          className="containers-source-check containers-source-check--ok"
        >
          Image reference found.
        </p>
      ) : null}
      {!showGitBranch && imageRefCheck.status === 'unavailable' ? (
        <p
          id="source-input-status"
          className={
            imageRefCheck.canAttemptDeploy
              ? 'containers-source-check containers-source-check--warn'
              : 'containers-source-check containers-source-check--err'
          }
          role="alert"
        >
          {imageRefCheck.canAttemptDeploy
            ? 'Registry did not confirm this image (you may need registry access). You can still try Build.'
            : 'Image not found in the registry.'}
        </p>
      ) : null}
      {!showGitBranch && imageRefCheck.status === 'error' ? (
        <p
          id="source-input-status"
          className="containers-source-check containers-source-check--warn"
          role="alert"
        >
          Could not verify image: {imageRefCheck.detail}
        </p>
      ) : null}
    </>
  )
}
