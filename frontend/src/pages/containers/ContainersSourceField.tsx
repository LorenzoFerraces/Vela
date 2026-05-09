import type { ImageRefCheckState } from './types'
import { sourceLooksLikeGitUrl } from './sourceKind'

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
  return (
    <>
      <input
        id="source-input"
        className="containers-form__input"
        type="text"
        autoComplete="off"
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
