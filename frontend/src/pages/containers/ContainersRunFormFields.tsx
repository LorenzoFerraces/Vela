import { VelaSparkIcon } from '../../components/VelaSparkIcon'

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

type ContainerPortFieldProps = {
  value: string
  onChange: (value: string) => void
  error?: string | null
  placeholder: string
}

function ContainerPortField({
  value,
  onChange,
  error,
  placeholder,
}: ContainerPortFieldProps) {
  return (
    <>
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
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? 'container-port-error' : undefined}
      />
      {error ? (
        <p
          id="container-port-error"
          className="containers-source-check containers-source-check--err"
          role="alert"
        >
          {error}
        </p>
      ) : null}
    </>
  )
}

type ContainersRunFormFieldsProps = {
  containerName: string
  onContainerNameChange: (value: string) => void
  containerPort: string
  onContainerPortChange: (value: string) => void
  portError?: string | null
}

export function ContainersRunFormFields({
  containerName,
  onContainerNameChange,
  containerPort,
  onContainerPortChange,
  portError,
}: ContainersRunFormFieldsProps) {
  return (
    <div className="containers-form__stack">
      <label className="containers-form__label" htmlFor="name-input">
        Container name (optional)
      </label>
      <input
        id="name-input"
        className="containers-form__input"
        type="text"
        value={containerName}
        onChange={(event) => onContainerNameChange(event.target.value)}
        placeholder="my-service"
        autoComplete="off"
      />

      <ContainerPortField
        value={containerPort}
        onChange={onContainerPortChange}
        error={portError}
        placeholder="80"
      />
    </div>
  )
}

type ContainersRunGitFieldsProps = ContainersRunFormFieldsProps & {
  gitBranch: string
  onGitBranchChange: (value: string) => void
  gitAnalysisLoading: boolean
  gitAnalysisError: string | null
  onAnalyzeGit: () => void
}

export function ContainersRunGitFields({
  containerName,
  onContainerNameChange,
  containerPort,
  onContainerPortChange,
  portError,
  gitBranch,
  onGitBranchChange,
  gitAnalysisLoading,
  gitAnalysisError,
  onAnalyzeGit,
}: ContainersRunGitFieldsProps) {
  return (
    <div className="containers-form__stack">
      <label className="containers-form__label" htmlFor="name-input">
        Container name (optional)
      </label>
      <div className="containers-form__name-row">
        <input
          id="name-input"
          className="containers-form__input containers-form__input--inline"
          type="text"
          value={containerName}
          onChange={(event) => onContainerNameChange(event.target.value)}
          placeholder="my-service"
          autoComplete="off"
        />
        <GitAnalysisButton
          loading={gitAnalysisLoading}
          onClick={onAnalyzeGit}
        />
      </div>

      <ContainerPortField
        value={containerPort}
        onChange={onContainerPortChange}
        error={portError}
        placeholder="5173"
      />

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
        autoComplete="off"
      />

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
    </div>
  )
}
