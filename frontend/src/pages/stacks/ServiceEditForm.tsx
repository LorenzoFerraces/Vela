import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  analyzeGitSource,
  formatApiError,
  uploadVolumeFolder,
  type BuildOverride,
  type ScalingPolicyRequest,
  type StackServiceCreate,
} from '../../api/client'
import BuildConfigModal from '../containers/BuildConfigModal'
import {
  buildOverrideFromAnalysis,
  languageLabel,
} from '../containers/buildOverride'
import { DeploySourceCombobox } from '../containers/DeploySourceCombobox'
import { useDeploySourceSelection } from '../containers/useDeploySourceSelection'
import { useImageRefAvailability } from '../containers/useImageRefAvailability'
import type { DeploySourceSelection } from '../containers/deploySourceTypes'
import {
  selectionShowsGitBranch,
  sourceLooksLikeGitUrl,
} from '../containers/deploySourceTypes'
import type { EnvVarRow, VolumeMountRow } from '../containers/runFormAdvanced'
import {
  createEmptyEnvRow,
  createEmptyVolumeMountRow,
  envRowsFromRecord,
  formatStartCommand,
  parseStartCommand,
  recordFromEnvRows,
  volumesFromRows,
} from '../containers/runFormAdvanced'
import { ContainersRunScalingFields } from '../containers/ContainersRunScalingFields'
import {
  detectServiceLinks,
  findServiceNameMatches,
  renderHighlightedValue,
} from './serviceLinkDetection'

export type ServiceFieldErrors = { name: string | null; source: string | null }

export function ServiceEditForm({
  service,
  index,
  fieldErrors,
  onUpdate,
  onPatch,
  onRemove,
  onClose,
  siblingNames,
  onSelectSibling,
}: {
  service: StackServiceCreate
  index: number
  fieldErrors: ServiceFieldErrors | null
  onUpdate: (index: number, field: keyof StackServiceCreate, value: unknown) => void
  onPatch: (index: number, patch: Partial<StackServiceCreate>) => void
  onRemove: (index: number) => void
  onClose: () => void
  siblingNames: string[]
  onSelectSibling: (serviceName: string) => void
}) {
  const [advancedOpen, setAdvancedOpen] = useState(
    () => Object.keys(service.env_vars || {}).length > 0,
  )
  const [pickingVolumeIndex, setPickingVolumeIndex] = useState<number | null>(null)
  const [buildConfigOpen, setBuildConfigOpen] = useState(false)
  const [buildConfigInitial, setBuildConfigInitial] = useState<BuildOverride | null>(
    null,
  )
  const [buildConfigBusy, setBuildConfigBusy] = useState(false)
  const [buildConfigError, setBuildConfigError] = useState<string | null>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const envRows = useMemo(
    () => envRowsFromRecord(service.env_vars || {}),
    [service.env_vars]
  )
  const commandStr = formatStartCommand(service.command)
  const volumeRows = useMemo(
    () => {
      const existing = (service.volumes || []).map((v) => ({
        ...createEmptyVolumeMountRow(),
        uploadId: v.upload_id,
        target: v.target,
        folderName: v.upload_id ? 'Uploaded folder' : null,
      }))
      return existing.length > 0 ? existing : [createEmptyVolumeMountRow()]
    },
    [service.volumes]
  )
  const scalingPolicy = service.scaling_policy as ScalingPolicyRequest | null

  const {
    listboxId,
    rootRef,
    selection,
    suggestions,
    listOpen,
    searchLoading,
    pastedGithubRepoPending,
    pastedGithubHint,
    displayValue,
    applySuggestion,
    tryCommitPastedGithubRepo,
    onInputChange,
    onInputFocus,
    setListOpen,
  } = useDeploySourceSelection()

  const { imageRefCheck, runImageRefAvailabilityCheck } = useImageRefAvailability(
    selection?.kind === 'image' ? selection.ref : ''
  )

  const initializedRef = useRef(false)

  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    if (!service.source_ref) return

    const sourceRef = service.source_ref
    if (service.source_kind === 'git' || sourceLooksLikeGitUrl(sourceRef)) {
      const branch = service.git_branch?.trim() || 'main'
      applySuggestion({
        kind: 'git',
        url: sourceRef,
        name: sourceRef,
        default_branch: branch,
      })
      if (service.source_kind !== 'git' || !service.git_branch) {
        onPatch(index, {
          source_kind: 'git',
          source_ref: sourceRef,
          git_branch: branch,
        })
      }
    } else if (service.source_kind === 'dockerfile_template') {
      applySuggestion({
        kind: 'dockerfile_template',
        id: sourceRef,
        name: sourceRef,
      })
    } else {
      applySuggestion({
        kind: 'image',
        ref: sourceRef,
        label: sourceRef,
      })
    }
  }, [
    service.source_ref,
    service.source_kind,
    service.git_branch,
    applySuggestion,
    index,
    onPatch,
  ])

  const commitSelection = useCallback(
    (sel: DeploySourceSelection | null) => {
      if (!sel) return
      switch (sel.kind) {
        case 'image':
          onPatch(index, {
            source_kind: 'image',
            source_ref: sel.ref,
            git_branch: null,
            build_override: null,
          })
          break
        case 'git':
          onPatch(index, {
            source_kind: 'git',
            source_ref: sel.url,
            git_branch: sel.defaultBranch || 'main',
          })
          break
        case 'dockerfile_template':
          onPatch(index, {
            source_kind: 'dockerfile_template',
            source_ref: sel.templateId,
            git_branch: null,
            build_override: null,
          })
          break
        default: {
          const _exhaustive: never = sel
          return _exhaustive
        }
      }
    },
    [index, onPatch]
  )

  function openBuildConfigModal(initial?: BuildOverride | null) {
    setBuildConfigInitial(initial ?? service.build_override ?? null)
    setBuildConfigError(null)
    setBuildConfigOpen(true)
  }

  async function onAnalyzeGitSource() {
    if (!service.source_ref.trim()) {
      setBuildConfigError('Choose a git repository first.')
      return
    }
    setBuildConfigBusy(true)
    setBuildConfigError(null)
    try {
      const analysis = await analyzeGitSource({
        git_url: service.source_ref.trim(),
        git_branch: service.git_branch?.trim() || 'main',
      })
      if (analysis.needs_manual_build_config) {
        openBuildConfigModal(buildOverrideFromAnalysis(analysis))
      }
    } catch (error) {
      setBuildConfigError(formatApiError(error))
    } finally {
      setBuildConfigBusy(false)
    }
  }

  const updateEnvRow = (rowIndex: number, patch: Partial<EnvVarRow>) => {
    const next = envRows.map((row, i) => (i === rowIndex ? { ...row, ...patch } : row))
    onUpdate(index, 'env_vars', recordFromEnvRows(next))
  }

  const addEnvRow = () => {
    const next = [...envRows, createEmptyEnvRow()]
    onUpdate(index, 'env_vars', recordFromEnvRows(next))
  }

  const removeEnvRow = (rowIndex: number) => {
    const next = envRows.filter((_, i) => i !== rowIndex)
    const cleaned = next.length > 0 ? next : [createEmptyEnvRow()]
    onUpdate(index, 'env_vars', recordFromEnvRows(cleaned))
  }

  const handleCommandChange = (value: string) => {
    onUpdate(index, 'command', parseStartCommand(value))
  }

  const updateVolumeRow = (rowIndex: number, patch: Partial<VolumeMountRow>) => {
    const next = volumeRows.map((row, i) => (i === rowIndex ? { ...row, ...patch } : row))
    onUpdate(index, 'volumes', volumesFromRows(next))
  }

  const addVolumeRow = () => {
    const next = [...volumeRows, createEmptyVolumeMountRow()]
    onUpdate(index, 'volumes', volumesFromRows(next))
  }

  const removeVolumeRow = (rowIndex: number) => {
    const next = volumeRows.filter((_, i) => i !== rowIndex)
    const cleaned = next.length > 0 ? next : [createEmptyVolumeMountRow()]
    onUpdate(index, 'volumes', volumesFromRows(cleaned))
  }

  const openFolderPicker = (rowIndex: number) => {
    setPickingVolumeIndex(rowIndex)
    folderInputRef.current?.click()
  }

  const onFolderSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    event.target.value = ''
    const fileList = event.target.files
    const rowIndex = pickingVolumeIndex
    setPickingVolumeIndex(null)
    if (!fileList || rowIndex === null) return

    const files = Array.from(fileList)
    if (files.length === 0) {
      updateVolumeRow(rowIndex, { error: 'Select a folder that contains at least one file.', uploading: false })
      return
    }

    updateVolumeRow(rowIndex, { uploading: true, error: null })

    try {
      const upload = await uploadVolumeFolder(files)
      updateVolumeRow(rowIndex, {
        uploadId: upload.upload_id,
        folderName: upload.folder_name,
        totalBytes: upload.total_bytes,
        uploading: false,
        error: null,
      })
    } catch (error) {
      updateVolumeRow(rowIndex, { uploading: false, error: formatApiError(error) })
    }
  }

  const handleScalingChange = (policy: ScalingPolicyRequest | null) => {
    onUpdate(index, 'scaling_policy', policy)
  }

  const serviceLinks = useMemo(
    () =>
      detectServiceLinks(service.env_vars, siblingNames, service.depends_on),
    [service.env_vars, siblingNames, service.depends_on],
  )

  return (
    <div className="containers-form stacks-builder__edit-form">
      <div className="stacks-builder__edit-form-actions">
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={(event) => {
            event.stopPropagation()
            onClose()
          }}
        >
          Close
        </button>
        <button
          type="button"
          className="btn btn--danger btn--sm"
          onClick={(event) => {
            event.stopPropagation()
            onRemove(index)
          }}
        >
          Remove
        </button>
      </div>

      <div className="containers-form__grid">
        <div className="containers-form__stack">
          <label
            className="containers-form__label"
            htmlFor={`svc-${index}-name`}
          >
            Service name
          </label>
          <input
            id={`svc-${index}-name`}
            className="containers-form__input"
            autoComplete="off"
            value={service.service_name || ''}
            onChange={(e) => onUpdate(index, 'service_name', e.target.value)}
            placeholder={`service-${index + 1}`}
          />
          {fieldErrors?.name ? (
            <p className="settings-banner settings-banner--err" role="alert">
              {fieldErrors.name}
            </p>
          ) : null}
        </div>

        <div className="containers-form__stack">
          <label
            className="containers-form__label"
            htmlFor={`svc-${index}-port`}
          >
            Container port
          </label>
          <input
            id={`svc-${index}-port`}
            type="number"
            className="containers-form__input"
            autoComplete="off"
            value={service.container_port ?? 80}
            onChange={(e) =>
              onUpdate(index, 'container_port', parseInt(e.target.value, 10) || 80)
            }
            min={1}
            max={65535}
          />
        </div>
      </div>

      <div className="containers-form__stack">
        <label className="containers-form__label" htmlFor="deploy-source-input">
          Deploy source
        </label>
        <DeploySourceCombobox
          listboxId={listboxId}
          rootRef={rootRef}
          displayValue={displayValue}
          selection={selection}
          suggestions={suggestions}
          listOpen={listOpen}
          searchLoading={searchLoading}
          pastedGithubRepoPending={pastedGithubRepoPending}
          pastedGithubHint={pastedGithubHint}
          imageRefCheck={imageRefCheck}
          onInputChange={onInputChange}
          onInputFocus={onInputFocus}
          onPickSuggestion={(s) => {
            applySuggestion(s)
            commitSelection(
              s.kind === 'image'
                ? { kind: 'image', ref: s.ref, label: s.label }
                : s.kind === 'git'
                  ? { kind: 'git', url: s.url, name: s.name, defaultBranch: s.default_branch }
                  : { kind: 'dockerfile_template', templateId: s.id, name: s.name }
            )
          }}
          onRequestImageCheck={runImageRefAvailabilityCheck}
          onCommitPastedGithubRepo={() => {
            const committed = tryCommitPastedGithubRepo()
            if (!committed) {
              return
            }
            applySuggestion(committed)
            commitSelection(
              committed.kind === 'image'
                ? { kind: 'image', ref: committed.ref, label: committed.label }
                : committed.kind === 'git'
                  ? {
                      kind: 'git',
                      url: committed.url,
                      name: committed.name,
                      defaultBranch: committed.default_branch,
                    }
                  : {
                       kind: 'dockerfile_template',
                       templateId: committed.id,
                       name: committed.name,
                    }
              )
            }}
            onListClose={() => setListOpen(false)}
        />
        {fieldErrors?.source ? (
          <p className="settings-banner settings-banner--err" role="alert">
            {fieldErrors.source}
          </p>
        ) : null}
      </div>

      {selectionShowsGitBranch(selection) ? (
        <div className="containers-form__stack">
          <label
            className="containers-form__label"
            htmlFor={`svc-${index}-branch`}
          >
            Git branch
          </label>
          <input
            id={`svc-${index}-branch`}
            className="containers-form__input"
            type="text"
            autoComplete="off"
            value={service.git_branch || 'main'}
            onChange={(e) => onUpdate(index, 'git_branch', e.target.value)}
            placeholder="main"
          />
          <div className="stacks-builder__build-actions">
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={buildConfigBusy || !service.source_ref.trim()}
              onClick={() => void onAnalyzeGitSource()}
            >
              {buildConfigBusy ? 'Analyzing…' : 'Analyze repo'}
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => openBuildConfigModal(service.build_override ?? null)}
            >
              Configure build
            </button>
          </div>
          {service.build_override ? (
            <p className="containers-muted containers-form__hint">
              Build override: {languageLabel(service.build_override.language)}
              {service.build_override.language_version
                ? ` ${service.build_override.language_version}`
                : ''}
              {service.build_override.package_manager
                ? ` · ${service.build_override.package_manager}`
                : ''}
              {service.build_override.build_subdir
                ? ` · ${service.build_override.build_subdir}`
                : ''}
            </p>
          ) : (
            <p className="containers-muted containers-form__hint">
              Optional when auto-detect cannot pick a language.
            </p>
          )}
          {buildConfigError ? (
            <p className="settings-banner settings-banner--err" role="alert">
              {buildConfigError}
            </p>
          ) : null}
        </div>
      ) : null}

      <label className="stacks-builder__checkbox">
        <input
          type="checkbox"
          checked={service.public_route || false}
          onChange={(e) => onUpdate(index, 'public_route', e.target.checked)}
        />
        Public route
      </label>

      {siblingNames.length > 0 ? (
        <div className="containers-form__stack">
          <p className="containers-form__label">Depends on</p>
          <div className="stacks-builder__depends-cards">
            {siblingNames.map((name) => {
              const checked = (service.depends_on || []).includes(name)
              return (
                <button
                  key={name}
                  type="button"
                  className={[
                    'stacks-builder__dep-card',
                    checked ? 'stacks-builder__dep-card--active' : '',
                  ].join(' ')}
                  onClick={() => {
                    const current = service.depends_on || []
                    const next = checked
                      ? current.filter((n) => n !== name)
                      : [...current, name]
                    onUpdate(index, 'depends_on', next.length > 0 ? next : null)
                  }}
                >
                  {name}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}

      <div className="containers-form__advanced">
        <input
          ref={folderInputRef}
          type="file"
          className="containers-form__folder-input"
          multiple
          onChange={onFolderSelected}
          {...{ webkitdirectory: '', directory: '' }}
          tabIndex={-1}
          aria-hidden="true"
        />
        <button
          type="button"
          className="btn btn--ghost containers-form__advanced-toggle"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          <span>Advanced Options</span>
          <span className="containers-form__advanced-chevron" aria-hidden="true">›</span>
        </button>
        {advancedOpen ? (
          <div className="containers-form__advanced-body">
            <p className="containers-form__label">Environment variables</p>
            <ul className="containers-env-list">
              {envRows.map((row, rowIndex) => {
                const matches = findServiceNameMatches(row.value, siblingNames)
                const previewParts = renderHighlightedValue(row.value, matches)
                return (
                  <li key={rowIndex} className="containers-env-list__row containers-env-list__row--stacked">
                    <div className="containers-env-list__fields">
                      <input
                        className="containers-form__input"
                        type="text"
                        autoComplete="off"
                        placeholder="KEY"
                        aria-label={`Environment variable name ${rowIndex + 1}`}
                        value={row.key}
                        onChange={(e) => updateEnvRow(rowIndex, { key: e.target.value })}
                      />
                      <input
                        className="containers-form__input"
                        type="text"
                        autoComplete="off"
                        placeholder="value"
                        aria-label={`Environment variable value ${rowIndex + 1}`}
                        value={row.value}
                        onChange={(e) => updateEnvRow(rowIndex, { value: e.target.value })}
                      />
                      <button
                        type="button"
                        className="btn btn--ghost btn--compact"
                        onClick={() => removeEnvRow(rowIndex)}
                        aria-label={`Remove environment variable ${rowIndex + 1}`}
                      >
                        Remove
                      </button>
                    </div>
                    {matches.length > 0 ? (
                      <p className="stacks-env-link-preview">
                        {previewParts.map((part) =>
                          part.highlighted ? (
                            <span key={part.key} className="stacks-env-link-preview__hit">
                              {part.text}
                            </span>
                          ) : (
                            <span key={part.key}>{part.text}</span>
                          ),
                        )}
                      </p>
                    ) : null}
                  </li>
                )
              })}
            </ul>
            <button
              type="button"
              className="btn btn--ghost btn--compact"
              onClick={addEnvRow}
            >
              Add variable
            </button>

            {serviceLinks.length > 0 ? (
              <div className="stacks-service-links">
                <p className="stacks-service-links__title">Service links</p>
                <ul className="stacks-service-links__list">
                  {serviceLinks.map((link) => (
                    <li
                      key={`${link.envKey}-${link.serviceName}`}
                      className="stacks-service-links__item"
                    >
                      <span>
                        {service.service_name || `service-${index + 1}`} →{' '}
                        <button
                          type="button"
                          className="stacks-service-links__target"
                          onClick={() => onSelectSibling(link.serviceName)}
                        >
                          {link.serviceName}
                        </button>{' '}
                        via <code>{link.envKey}</code>
                      </span>
                      {!link.inDependsOn ? (
                        <span className="stacks-service-links__hint">
                          Not listed in Depends on
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <label className="containers-form__label" htmlFor={`svc-${index}-command`}>
              Start command
            </label>
            <input
              id={`svc-${index}-command`}
              className="containers-form__input"
              type="text"
              autoComplete="off"
              placeholder="Optional CMD override"
              value={commandStr}
              onChange={(e) => handleCommandChange(e.target.value)}
            />
            <p className="containers-muted containers-form__hint">
              Overrides the container CMD when set.
            </p>

            <p className="containers-form__label">Volumes (read-only)</p>
            <ul className="containers-env-list">
              {volumeRows.map((row, rowIndex) => (
                <li key={rowIndex} className="containers-env-list__row containers-env-list__row--volume">
                  <div className="containers-volume-row">
                    <button
                      type="button"
                      className="btn btn--ghost btn--compact"
                      disabled={row.uploading}
                      onClick={() => openFolderPicker(rowIndex)}
                    >
                      {row.uploading
                        ? 'Uploading…'
                        : row.folderName
                          ? 'Change folder'
                          : 'Choose folder'}
                    </button>
                    {row.folderName ? (
                      <span className="containers-muted containers-volume-row__meta">
                        {row.folderName}
                      </span>
                    ) : null}
                    <input
                      className="containers-form__input"
                      type="text"
                      autoComplete="off"
                      placeholder="/path/in/container"
                      aria-label={`Volume target ${rowIndex + 1}`}
                      value={row.target}
                      onChange={(e) => updateVolumeRow(rowIndex, { target: e.target.value })}
                    />
                    <button
                      type="button"
                      className="btn btn--ghost btn--compact"
                      onClick={() => removeVolumeRow(rowIndex)}
                      aria-label={`Remove volume ${rowIndex + 1}`}
                    >
                      Remove
                    </button>
                  </div>
                  {row.error ? (
                    <p className="settings-banner settings-banner--err" role="alert">
                      {row.error}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="btn btn--ghost btn--compact"
              onClick={addVolumeRow}
            >
              Add volume
            </button>

            <ContainersRunScalingFields
              scalingPolicy={scalingPolicy}
              onScalingPolicyChange={handleScalingChange}
            />
          </div>
        ) : null}
      </div>

      <BuildConfigModal
        open={buildConfigOpen}
        initial={buildConfigInitial}
        onCancel={() => setBuildConfigOpen(false)}
        onConfirm={(override) => {
          onPatch(index, { build_override: override })
          setBuildConfigOpen(false)
        }}
      />
    </div>
  )
}
