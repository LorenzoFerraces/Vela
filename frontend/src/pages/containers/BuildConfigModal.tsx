import { useEffect, useId, useRef, useState } from 'react'
import type { BuildOverride, BuildOverrideLanguage } from '../../api/client'
import {
  BUILD_OVERRIDE_LANGUAGES,
  defaultLanguageVersion,
  defaultPackageManager,
  emptyBuildOverride,
  formatStartCommand,
  isBuildOverrideLanguage,
  languageLabel,
  normalizeBuildOverride,
  packageManagersForLanguage,
  parseStartCommand,
} from './buildOverride'

type BuildConfigModalProps = {
  open: boolean
  onCancel: () => void
  onConfirm: (override: BuildOverride) => void
  initial?: BuildOverride | null
}

type FormState = {
  language: BuildOverrideLanguage
  languageVersion: string
  packageManager: string
  buildSubdir: string
  startCommand: string
}

function formStateFromOverride(override: BuildOverride | null | undefined): FormState {
  const base = override ? normalizeBuildOverride(override) : emptyBuildOverride()
  return {
    language: base.language,
    languageVersion: base.language_version ?? '',
    packageManager: base.package_manager ?? defaultPackageManager(base.language) ?? '',
    buildSubdir: base.build_subdir ?? '',
    startCommand: formatStartCommand(base.start_command),
  }
}

export default function BuildConfigModal({
  open,
  onCancel,
  onConfirm,
  initial = null,
}: BuildConfigModalProps) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const [form, setForm] = useState<FormState>(() => formStateFromOverride(initial))
  const [prevOpen, setPrevOpen] = useState(open)
  const [prevInitial, setPrevInitial] = useState(initial)

  if (open !== prevOpen || initial !== prevInitial) {
    setPrevOpen(open)
    setPrevInitial(initial)
    if (open) {
      setForm(formStateFromOverride(initial))
    }
  }

  useEffect(() => {
    if (!open) {
      return
    }
    const previouslyFocused = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCancel()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      previouslyFocused?.focus()
    }
  }, [open, onCancel])

  if (!open) {
    return null
  }

  const packageManagers = packageManagersForLanguage(form.language)

  function setLanguage(language: BuildOverrideLanguage) {
    setForm((previous) => ({
      ...previous,
      language,
      languageVersion: defaultLanguageVersion(language),
      packageManager: defaultPackageManager(language) ?? '',
    }))
  }

  function handleConfirm() {
    onConfirm(
      normalizeBuildOverride({
        language: form.language,
        language_version: form.languageVersion,
        package_manager: packageManagers.length > 0 ? form.packageManager : null,
        build_subdir: form.buildSubdir,
        start_command: parseStartCommand(form.startCommand),
      }),
    )
  }

  return (
    <div className="stacks-modal-backdrop" role="presentation" onClick={onCancel}>
      <div
        ref={dialogRef}
        className="stacks-modal stacks-modal--build-config"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="stacks-modal__header">
          <h2 id={titleId} className="stacks-modal__title">
            Build configuration
          </h2>
          <p className="stacks-modal__lead">
            Choose language and build settings so Vela can generate a Dockerfile.
          </p>
        </header>

        <div className="stacks-modal__body">
          <div className="containers-form__stack">
            <label className="containers-form__label" htmlFor="build-config-language">
              Language
            </label>
            <select
              id="build-config-language"
                  className="containers-form__input"
              value={form.language}
              onChange={(event) => {
                const value = event.target.value
                if (isBuildOverrideLanguage(value)) {
                  setLanguage(value)
                }
              }}
            >
              {BUILD_OVERRIDE_LANGUAGES.map((language) => (
                <option key={language} value={language}>
                  {languageLabel(language)}
                </option>
              ))}
            </select>
          </div>

          <div className="containers-form__grid">
            <div className="containers-form__stack">
              <label
                className="containers-form__label"
                htmlFor="build-config-version"
              >
                Version (optional)
              </label>
              <input
                id="build-config-version"
                className="containers-form__input"
                type="text"
                value={form.languageVersion}
                onChange={(event) =>
                  setForm((previous) => ({
                    ...previous,
                    languageVersion: event.target.value,
                  }))
                }
                placeholder={defaultLanguageVersion(form.language)}
              />
            </div>

            {packageManagers.length > 0 ? (
              <div className="containers-form__stack">
                <label
                  className="containers-form__label"
                  htmlFor="build-config-package-manager"
                >
                  Package manager
                </label>
                <select
                  id="build-config-package-manager"
              className="containers-form__input"
                  value={form.packageManager}
                  onChange={(event) =>
                    setForm((previous) => ({
                      ...previous,
                      packageManager: event.target.value,
                    }))
                  }
                >
                  {packageManagers.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <div className="containers-form__stack" aria-hidden="true" />
            )}
          </div>

          <div className="containers-form__stack">
            <label className="containers-form__label" htmlFor="build-config-subdir">
              Build subdirectory (optional)
            </label>
            <input
              id="build-config-subdir"
              className="containers-form__input"
              type="text"
              value={form.buildSubdir}
              onChange={(event) =>
                setForm((previous) => ({
                  ...previous,
                  buildSubdir: event.target.value,
                }))
              }
              placeholder="backend"
            />
            <p className="containers-form__hint">
              Relative path when the app lives under a monorepo folder.
            </p>
          </div>

          <div className="containers-form__stack">
            <label
              className="containers-form__label"
              htmlFor="build-config-start-command"
            >
              Start command (optional)
            </label>
            <input
              id="build-config-start-command"
              className="containers-form__input"
              type="text"
              value={form.startCommand}
              onChange={(event) =>
                setForm((previous) => ({
                  ...previous,
                  startCommand: event.target.value,
                }))
              }
              placeholder="java -jar app.jar"
            />
            <p className="containers-form__hint">
              Space-separated tokens for the container CMD.
            </p>
          </div>
        </div>

        <footer className="stacks-modal__footer">
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn btn--primary" onClick={handleConfirm}>
            Save build config
          </button>
        </footer>
      </div>
    </div>
  )
}
