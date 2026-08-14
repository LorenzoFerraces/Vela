import { useEffect, useId, useRef } from 'react'
import type { StackServiceCreate } from '../../api/client'

type ComposeImportReviewModalProps = {
  stackName: string
  services: StackServiceCreate[]
  warnings: string[]
  onChangeServices: (services: StackServiceCreate[]) => void
  onBack: () => void
  onContinue: () => void
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

export default function ComposeImportReviewModal({
  stackName,
  services,
  warnings,
  onChangeServices,
  onBack,
  onContinue,
}: ComposeImportReviewModalProps) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onBack()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      previouslyFocused?.focus()
    }
  }, [onBack])

  return (
    <div className="stacks-modal-backdrop" role="presentation" onClick={onBack}>
      <div
        ref={dialogRef}
        className="stacks-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="stacks-modal__header">
          <h2 id={titleId} className="stacks-modal__title">
            Review imported services
          </h2>
          <p className="stacks-modal__lead">
            Stack <strong>{stackName || 'imported-stack'}</strong> — edit before opening the
            builder.
          </p>
        </header>

        {warnings.length > 0 ? (
          <div className="containers-banner containers-banner--ok stacks-modal__warnings">
            <p className="containers-banner__text">Parse warnings:</p>
            <ul className="containers-banner__list">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="stacks-modal__body">
          {services.map((service, index) => {
            const entries = envEntries(service.env_vars)
            return (
              <article key={`${service.service_name}-${index}`} className="stacks-modal__service">
                <div className="containers-form__grid">
                  <div className="containers-form__stack">
                    <label
                      className="containers-form__label"
                      htmlFor={`import-svc-${index}-name`}
                    >
                      Service name
                    </label>
                    <input
                      id={`import-svc-${index}-name`}
                      className="containers-form__input"
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
                      htmlFor={`import-svc-${index}-port`}
                    >
                      Container port
                    </label>
                    <input
                      id={`import-svc-${index}-port`}
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
                    htmlFor={`import-svc-${index}-source`}
                  >
                    Source ({service.source_kind})
                  </label>
                  <input
                    id={`import-svc-${index}-source`}
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
                      htmlFor={`import-svc-${index}-branch`}
                    >
                      Git branch
                    </label>
                    <input
                      id={`import-svc-${index}-branch`}
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
          })}
        </div>

        <footer className="stacks-modal__footer">
          <button type="button" className="btn btn--ghost" onClick={onBack}>
            Back
          </button>
          <button type="button" className="btn btn--primary" onClick={onContinue}>
            Continue to builder
          </button>
        </footer>
      </div>
    </div>
  )
}
