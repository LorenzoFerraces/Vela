import { VelaSparkIcon } from '../../components/VelaSparkIcon'

type ContainersRunFormFieldsProps = {
  showGitBranch: boolean
  containerName: string
  onContainerNameChange: (value: string) => void
  gitBranch: string
  onGitBranchChange: (value: string) => void
  containerPort: string
  onContainerPortChange: (value: string) => void
  gitAnalysisLoading?: boolean
  gitAnalysisError?: string | null
  onAnalyzeGit?: () => void
}

function GitAnalysisButton({
  loading,
  onClick,
}: {
  loading: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className="btn btn--ghost containers-form__analyze-btn vela-icon-box"
      onClick={onClick}
      disabled={loading}
      aria-label="Analyze repository"
      title="Analyze this repo and pre-fill deploy settings"
    >
      <VelaSparkIcon />
    </button>
  )
}

export function ContainersRunFormFields({
  showGitBranch,
  containerName,
  onContainerNameChange,
  gitBranch,
  onGitBranchChange,
  containerPort,
  onContainerPortChange,
  gitAnalysisLoading = false,
  gitAnalysisError = null,
  onAnalyzeGit,
}: ContainersRunFormFieldsProps) {
  return (
    <div className="containers-form__stack">
      <label className="containers-form__label" htmlFor="name-input">
        Container name (optional)
      </label>
      {showGitBranch && onAnalyzeGit ? (
        <div className="containers-form__name-row">
          <input
            id="name-input"
            className="containers-form__input containers-form__input--inline"
            type="text"
            value={containerName}
            onChange={(event) => onContainerNameChange(event.target.value)}
            placeholder="my-service"
          />
          <GitAnalysisButton
            loading={gitAnalysisLoading}
            onClick={onAnalyzeGit}
          />
        </div>
      ) : (
        <input
          id="name-input"
          className="containers-form__input"
          type="text"
          value={containerName}
          onChange={(event) => onContainerNameChange(event.target.value)}
          placeholder="my-service"
        />
      )}

      <label
        className="containers-form__label"
        htmlFor="container-port-input"
      >
        Container port
      </label>
      <input
        id="container-port-input"
        className="containers-form__input"
        type="number"
        min={1}
        max={65535}
        value={containerPort}
        onChange={(event) => onContainerPortChange(event.target.value)}
        placeholder={showGitBranch ? '5173' : '80'}
      />

      {showGitBranch ? (
        <>
          <label className="containers-form__label" htmlFor="branch-input">
            Git branch
          </label>
          <input
            id="branch-input"
            className="containers-form__input"
            type="text"
            value={gitBranch}
            onChange={(event) => onGitBranchChange(event.target.value)}
            placeholder="main"
          />
        </>
      ) : null}

      {showGitBranch ? (
        <>
          {gitAnalysisLoading ? (
            <p className="containers-muted containers-form__hint" role="status">
              Analyzing repository…
            </p>
          ) : null}
          {gitAnalysisError ? (
            <p
              className="containers-source-check containers-source-check--warn"
              role="alert"
            >
              {gitAnalysisError}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
