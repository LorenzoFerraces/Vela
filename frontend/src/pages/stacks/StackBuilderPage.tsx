import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  createStack,
  formatApiError,
  getStack,
  uploadVolumeFolder,
  updateStack,
  type ScalingPolicyRequest,
  type StackServiceCreate,
} from '../../api/client'
import { DeploySourceCombobox } from '../containers/DeploySourceCombobox'
import { useDeploySourceSelection } from '../containers/useDeploySourceSelection'
import { useImageRefAvailability } from '../containers/useImageRefAvailability'
import type { DeploySourceSelection } from '../containers/deploySourceTypes'
import type { EnvVarRow, VolumeMountRow } from '../containers/runFormAdvanced'
import {
  createEmptyVolumeMountRow,
  envRowsFromRecord,
  formatStartCommand,
  parseStartCommand,
  recordFromEnvRows,
  volumesFromRows,
} from '../containers/runFormAdvanced'
import { ContainersRunScalingFields } from '../containers/ContainersRunScalingFields'
import StackVisualizer from './StackVisualizer'

type Banner = { tone: 'ok' | 'err'; text: string } | null

function ServiceEditForm({
  service,
  index,
  onUpdate,
  onRemove,
  siblingNames,
}: {
  service: StackServiceCreate
  index: number
  onUpdate: (index: number, field: keyof StackServiceCreate, value: unknown) => void
  onRemove: (index: number) => void
  siblingNames: string[]
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [pickingVolumeIndex, setPickingVolumeIndex] = useState<number | null>(null)
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
  } = useDeploySourceSelection()

  const { imageRefCheck, runImageRefAvailabilityCheck } = useImageRefAvailability(
    selection?.kind === 'image' ? selection.ref : ''
  )

  const initializedRef = useRef(false)

  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    if (service.source_ref) {
      if (service.source_kind === 'git') {
        const url = service.source_ref
        applySuggestion({
          kind: 'git',
          url,
          name: url,
          default_branch: 'main',
        })
      } else if (service.source_kind === 'dockerfile_template') {
        applySuggestion({
          kind: 'dockerfile_template',
          id: service.source_ref,
          name: service.source_ref,
        })
      } else {
        applySuggestion({
          kind: 'image',
          ref: service.source_ref,
          label: service.source_ref,
        })
      }
    }
  }, [service.source_ref, service.source_kind, applySuggestion])

  const commitSelection = useCallback(
    (sel: DeploySourceSelection | null) => {
      if (!sel) return
      switch (sel.kind) {
        case 'image':
          onUpdate(index, 'source_kind', 'image')
          onUpdate(index, 'source_ref', sel.ref)
          break
        case 'git':
          onUpdate(index, 'source_kind', 'git')
          onUpdate(index, 'source_ref', sel.url)
          break
        case 'dockerfile_template':
          onUpdate(index, 'source_kind', 'dockerfile_template')
          onUpdate(index, 'source_ref', sel.templateId)
          break
      }
    },
    [index, onUpdate]
  )

  const updateEnvRow = (rowIndex: number, patch: Partial<EnvVarRow>) => {
    const next = envRows.map((row, i) => (i === rowIndex ? { ...row, ...patch } : row))
    onUpdate(index, 'env_vars', recordFromEnvRows(next))
  }

  const addEnvRow = () => {
    const next = [...envRows, { key: '', value: '' }]
    onUpdate(index, 'env_vars', recordFromEnvRows(next))
  }

  const removeEnvRow = (rowIndex: number) => {
    const next = envRows.filter((_, i) => i !== rowIndex)
    const cleaned = next.length > 0 ? next : [{ key: '', value: '' }]
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

  return (
    <div className="containers-form stacks-builder__edit-form">
      <button
        type="button"
        className="btn btn--danger btn--sm"
        onClick={(e) => { e.stopPropagation(); onRemove(index); }}
        style={{ alignSelf: 'flex-end', marginBottom: '0.5rem' }}
      >
        Remove
      </button>

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
            value={service.service_name || ''}
            onChange={(e) => onUpdate(index, 'service_name', e.target.value)}
            placeholder={`service-${index + 1}`}
          />
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
            value={service.container_port ?? 80}
            onChange={(e) =>
              onUpdate(index, 'container_port', parseInt(e.target.value, 10))
            }
            min={1}
            max={65535}
          />
        </div>
      </div>

      <div className="containers-form__stack">
        <label className="containers-form__label">Source</label>
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
        />
      </div>

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
          <span>Advanced options</span>
          <span className="containers-form__advanced-chevron" aria-hidden="true">›</span>
        </button>
        {advancedOpen ? (
          <div className="containers-form__advanced-body">
            <p className="containers-form__label">Environment variables</p>
            <ul className="containers-env-list">
              {envRows.map((row, rowIndex) => (
                <li key={rowIndex} className="containers-env-list__row">
                  <input
                    className="containers-form__input"
                    type="text"
                    placeholder="KEY"
                    aria-label={`Environment variable name ${rowIndex + 1}`}
                    value={row.key}
                    onChange={(e) => updateEnvRow(rowIndex, { key: e.target.value })}
                  />
                  <input
                    className="containers-form__input"
                    type="text"
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
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="btn btn--ghost btn--compact"
              onClick={addEnvRow}
            >
              Add variable
            </button>

            <label className="containers-form__label" htmlFor={`svc-${index}-command`}>
              Start command
            </label>
            <input
              id={`svc-${index}-command`}
              className="containers-form__input"
              type="text"
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
    </div>
  )
}

export default function StackBuilderPage() {
  const { id: editId } = useParams<{ id?: string }>()
  const navigate = useNavigate()
  const [services, setServices] = useState<StackServiceCreate[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [highlightIndex, setHighlightIndex] = useState<number | null>(null)
  const [listLoading, setListLoading] = useState(!!editId)
  const [banner, setBanner] = useState<Banner>(null)
  const [stackName, setStackName] = useState('')

  useEffect(() => {
    if (!editId) return
    ;(async () => {
      try {
        const stack = await getStack(editId)
        setStackName(stack.name)
        setServices(
          stack.services.map((s) => ({
            service_name: s.service_name,
            source_kind: s.source_kind,
            source_ref: s.source_ref,
            container_port: s.container_port,
            env_vars: s.env_vars,
            command: s.command,
            public_route: s.public_route,
            depends_on: s.depends_on,
            volumes: s.volumes,
            scaling_policy: s.scaling_policy,
          }))
        )
      } catch (err) {
        setBanner({ tone: 'err', text: formatApiError(err) })
      } finally {
        setListLoading(false)
      }
    })()
  }, [editId])

  const updateService = useCallback(
    (index: number, field: keyof StackServiceCreate, value: unknown) => {
      setServices((prev) =>
        prev.map((s, i) => (i === index ? { ...s, [field]: value } : s))
      )
    },
    []
  )

  const removeService = useCallback(
    (index: number) => {
      setServices((prev) => prev.filter((_, i) => i !== index))
      setSelectedIndex((prev) => {
        if (prev === index) return null
        if (prev !== null && prev > index) return prev - 1
        return prev
      })
    },
    []
  )

  function addService() {
    const newService: StackServiceCreate = {
      service_name: '',
      source_kind: 'image',
      source_ref: '',
      container_port: 80,
      public_route: false,
    }
    setServices((prev) => {
      const next = [...prev, newService]
      const newIndex = next.length - 1
      setSelectedIndex(newIndex)
      setHighlightIndex(newIndex)
      setTimeout(() => setHighlightIndex(null), 2000)
      return next
    })
  }

  async function handleSave() {
    if (services.length === 0) {
      setBanner({ tone: 'err', text: 'Stack must have at least one service.' })
      return
    }
    try {
      if (editId) {
        await updateStack(editId, {
          name: stackName || 'untitled-stack',
          services: services,
        })
      } else {
        await createStack({
          name: stackName || 'untitled-stack',
          services: services,
        })
      }
      navigate('/stacks')
    } catch (err) {
      setBanner({ tone: 'err', text: formatApiError(err) })
    }
  }

  const selectedService =
    selectedIndex !== null ? services[selectedIndex] : null

  return (
    <section className="stacks-builder-page">
      <h1 className="containers-page__title">
        {editId ? 'Edit Stack' : 'New Stack'}
      </h1>
      <p className="containers-page__lead">
        Define services and their dependencies, then deploy as a group.
      </p>

      <form className="containers-form" onSubmit={(e) => e.preventDefault()}>
        <label
          className="containers-form__label"
          htmlFor="stack-name-input"
        >
          Stack name
        </label>
        <input
          id="stack-name-input"
          className="containers-form__input"
          placeholder="my-stack"
          value={stackName}
          onChange={(e) => setStackName(e.target.value)}
        />
      </form>

      {banner ? (
        <div
          className={
            banner.tone === 'ok'
              ? 'containers-banner containers-banner--ok'
              : 'containers-banner containers-banner--err'
          }
          role={banner.tone === 'err' ? 'alert' : undefined}
        >
          <p className="containers-banner__text">{banner.text}</p>
        </div>
      ) : null}

      {listLoading ? (
        <p className="containers-muted">Loading…</p>
      ) : (
        <div className="stacks-builder__split">
          <div className="stacks-builder__form-col">
            <h2 className="containers-page__subtitle">Services</h2>

            {services.length === 0 ? (
              <p className="containers-muted">
                No services yet. Add one to get started.
              </p>
            ) : (
              <>
                <ul className="stacks-builder__list" role="list">
                  {services.map((service, index) => {
                    if (selectedIndex === index) return null
                    return (
                      <li
                        key={index}
                        className={[
                          'stacks-builder__list-item',
                          highlightIndex === index
                            ? 'stacks-builder__list-item--highlight'
                            : '',
                        ]
                          .filter(Boolean)
                          .join()}
                        role="button"
                        tabIndex={0}
                        onClick={() => setSelectedIndex(index)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            setSelectedIndex(index)
                          }
                        }}
                      >
                        {service.service_name || `service-${index + 1}`}
                      </li>
                    )
                  })}
                </ul>

                {selectedService !== null && (
                  <ServiceEditForm
                    key={selectedIndex}
                    service={selectedService}
                    index={selectedIndex!}
                    onUpdate={updateService}
                    onRemove={removeService}
                    siblingNames={services
                      .filter((_, i) => i !== selectedIndex)
                      .map((s) => s.service_name)
                      .filter((n): n is string => !!n && n.length > 0)}
                  />
                )}
              </>
            )}

            <div className="stacks-builder__actions">
              <button
                type="button"
                className="btn btn--ghost"
                onClick={addService}
              >
                + Add Service
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={handleSave}
              >
                Save Stack
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => navigate('/stacks')}
              >
                Cancel
              </button>
            </div>
          </div>

          <div className="stacks-builder__graph-col">
            {services.length > 0 ? (
              <StackVisualizer
                services={services}
                highlightedIndex={highlightIndex}
                selectedIndex={selectedIndex}
                onNodeClick={(index) => setSelectedIndex(index)}
                onDependencyChange={(serviceIndex, dependsOn) => {
                  updateService(serviceIndex, 'depends_on', dependsOn)
                }}
              />
            ) : (
              <div className="stacks-visualizer">
                <div className="stacks-visualizer__flow containers-muted">
                  Add services to see the graph
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
