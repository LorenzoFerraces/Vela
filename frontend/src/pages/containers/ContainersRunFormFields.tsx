type ContainersRunFormFieldsProps = {
  showGitBranch: boolean
  containerName: string
  onContainerNameChange: (value: string) => void
  gitBranch: string
  onGitBranchChange: (value: string) => void
  containerPort: string
  onContainerPortChange: (value: string) => void
}

export function ContainersRunFormFields({
  showGitBranch,
  containerName,
  onContainerNameChange,
  gitBranch,
  onGitBranchChange,
  containerPort,
  onContainerPortChange,
}: ContainersRunFormFieldsProps) {
  if (showGitBranch) {
    return (
      <div className="containers-form__grid">
        <div>
          <label className="containers-form__label" htmlFor="name-input">
            Container name (optional)
          </label>
          <input
            id="name-input"
            className="containers-form__input"
            type="text"
            value={containerName}
            onChange={(e) => onContainerNameChange(e.target.value)}
            placeholder="my-service"
          />
        </div>
        <div>
          <label className="containers-form__label" htmlFor="branch-input">
            Git branch
          </label>
          <input
            id="branch-input"
            className="containers-form__input"
            type="text"
            value={gitBranch}
            onChange={(e) => onGitBranchChange(e.target.value)}
            placeholder="main"
          />
        </div>
        <div>
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
            onChange={(e) => onContainerPortChange(e.target.value)}
            placeholder="5173"
            aria-describedby="container-port-hint"
          />
          <p
            id="container-port-hint"
            className="containers-muted containers-form__hint"
          >
            Must match the dev server port (e.g. Vite 5173, or{' '}
            <code>server.port</code> in vite.config).
          </p>
        </div>
      </div>
    )
  }

  return (
    <>
      <label className="containers-form__label" htmlFor="name-input">
        Container name (optional)
      </label>
      <input
        id="name-input"
        className="containers-form__input"
        type="text"
        value={containerName}
        onChange={(e) => onContainerNameChange(e.target.value)}
        placeholder="my-service"
      />
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
        onChange={(e) => onContainerPortChange(e.target.value)}
        placeholder="80"
        aria-describedby="container-port-hint-image"
      />
      <p
        id="container-port-hint-image"
        className="containers-muted containers-form__hint"
      >
        Port your app listens on inside the container (Traefik target when using a
        public URL without host port publish).
      </p>
    </>
  )
}
