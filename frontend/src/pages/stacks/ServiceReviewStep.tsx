import type { StackServiceCreate } from '../../api/client'

export type ServiceReviewStepProps = {
  stackName: string
  services: StackServiceCreate[]
  warnings: string[]
  originLabel: string
  creating: boolean
  error: string | null
  onChangeStackName: (stackName: string) => void
  onChangeServices: (services: StackServiceCreate[]) => void
  onBack: () => void
  onCreate: () => void
}

function updateServiceAt(
  services: StackServiceCreate[],
  index: number,
  patch: Partial<StackServiceCreate>,
): StackServiceCreate[] {
  return services.map((service, serviceIndex) =>
    serviceIndex === index ? { ...service, ...patch } : service,
  )
}

function envEntries(envVars: Record<string, string> | undefined): [string, string][] {
  return Object.entries(envVars || {})
}

export default function ServiceReviewStep({
  stackName,
  services,
  warnings,
  originLabel,
  creating,
  error,
  onChangeStackName,
  onChangeServices,
  onBack,
  onCreate,
}: ServiceReviewStepProps) {
  return (
    <>
      {warnings.length > 0 ? (
        <div className="containers-banner containers-banner--ok stacks-modal__warnings">
          <p className="containers-banner__text">Parse warnings:</p>
          <ul className="containers-banner__list">
            {warnings.map((warning, index) => (
              <li key={`${warning}-${index}`}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="new-stack-review__origin">{originLabel}</p>

      <div className="stacks-modal__body">
        <div className="containers-form__stack">
          <label className="containers-form__label" htmlFor="new-stack-review-name">
            Stack name
          </label>
          <input
            id="new-stack-review-name"
            className="containers-form__input"
            autoComplete="off"
            placeholder="my-stack"
            value={stackName}
            onChange={(event) => onChangeStackName(event.target.value)}
          />
        </div>

        {services.length === 0 ? (
          <p className="containers-muted">No services to review.</p>
        ) : (
          services.map((service, index) => {
            const entries = envEntries(service.env_vars)
            return (
              <article key={`${service.service_name}-${index}`} className="stacks-modal__service">
                <div className="containers-form__grid">
                  <div className="containers-form__stack">
                    <label
                      className="containers-form__label"
                      htmlFor={`review-svc-${index}-name`}
                    >
                      Service name
                    </label>
                    <input
                      id={`review-svc-${index}-name`}
                      className="containers-form__input"
                      autoComplete="off"
                      value={service.service_name}
                      onChange={(event) =>
                        onChangeServices(
                          updateServiceAt(services, index, {
                            service_name: event.target.value,
                          }),
                        )
                      }
                    />
                  </div>
                  <div className="containers-form__stack">
                    <label
                      className="containers-form__label"
                      htmlFor={`review-svc-${index}-port`}
                    >
                      Container port
                    </label>
                    {/* ponytail: clearing snaps back to the default (|| N); true empty-state editing is a product call */}
                    <input
                      id={`review-svc-${index}-port`}
                      type="number"
                      className="containers-form__input"
                      min={1}
                      max={65535}
                      value={service.container_port ?? 80}
                      onChange={(event) =>
                        onChangeServices(
                          updateServiceAt(services, index, {
                            container_port: Number.parseInt(event.target.value, 10) || 80,
                          }),
                        )
                      }
                    />
                  </div>
                </div>

                <div className="containers-form__stack">
                  <label
                    className="containers-form__label"
                    htmlFor={`review-svc-${index}-source`}
                  >
                    Source ({service.source_kind})
                  </label>
                  <input
                    id={`review-svc-${index}-source`}
                    className="containers-form__input"
                    value={service.source_ref}
                    onChange={(event) =>
                      onChangeServices(
                        updateServiceAt(services, index, {
                          source_ref: event.target.value,
                        }),
                      )
                    }
                  />
                </div>

                {service.source_kind === 'git' ? (
                  <div className="containers-form__stack">
                    <label
                      className="containers-form__label"
                      htmlFor={`review-svc-${index}-branch`}
                    >
                      Git branch
                    </label>
                    <input
                      id={`review-svc-${index}-branch`}
                      className="containers-form__input"
                      type="text"
                      value={service.git_branch || 'main'}
                      onChange={(event) =>
                        onChangeServices(
                          updateServiceAt(services, index, {
                            git_branch: event.target.value,
                          }),
                        )
                      }
                      placeholder="main"
                    />
                    {service.build_override ? (
                      <p className="containers-muted containers-form__hint">
                        Build override set ({service.build_override.language}
                        {service.build_override.language_version
                          ? ` ${service.build_override.language_version}`
                          : ''}
                        ). Edit in the builder if needed.
                      </p>
                    ) : null}
                  </div>
                ) : null}

                <label className="stacks-builder__checkbox">
                  <input
                    type="checkbox"
                    checked={service.public_route || false}
                    onChange={(event) =>
                      onChangeServices(
                        updateServiceAt(services, index, {
                          public_route: event.target.checked,
                        }),
                      )
                    }
                  />
                  Public route
                </label>

                {(service.depends_on?.length ?? 0) > 0 ? (
                  <p className="containers-muted stacks-modal__depends">
                    Depends on: {(service.depends_on || []).join(', ')}
                  </p>
                ) : null}

                {entries.length > 0 ? (
                  <div className="containers-form__stack">
                    <p className="containers-form__label">Environment variables</p>
                    <ul className="containers-env-list">
                      {entries.map(([key, value], entryIndex) => (
                        <li key={`${key}-${entryIndex}`} className="containers-env-list__row">
                          <input
                            className="containers-form__input"
                            type="text"
                            aria-label={`${service.service_name} env name ${entryIndex + 1}`}
                            value={key}
                            onChange={(event) => {
                              const nextEntries = [...entries]
                              nextEntries[entryIndex] = [event.target.value, value]
                              onChangeServices(
                                updateServiceAt(services, index, {
                                  env_vars: Object.fromEntries(nextEntries),
                                }),
                              )
                            }}
                          />
                          <input
                            className="containers-form__input"
                            type="text"
                            aria-label={`${service.service_name} env value ${entryIndex + 1}`}
                            value={value}
                            onChange={(event) => {
                              const nextEntries = [...entries]
                              nextEntries[entryIndex] = [key, event.target.value]
                              onChangeServices(
                                updateServiceAt(services, index, {
                                  env_vars: Object.fromEntries(nextEntries),
                                }),
                              )
                            }}
                          />
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </article>
            )
          })
        )}
      </div>

      {error ? (
        <p className="settings-banner settings-banner--err new-stack-review__error" role="alert">
          {error}
        </p>
      ) : null}

      <footer className="stacks-modal__footer">
        <button type="button" className="btn btn--ghost" onClick={onBack} disabled={creating}>
          Back
        </button>
        <button
          type="button"
          className="btn btn--primary"
          onClick={onCreate}
          disabled={creating || services.length === 0}
        >
          {creating ? 'Creating…' : 'Create stack'}
        </button>
      </footer>
    </>
  )
}
