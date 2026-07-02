import { useRef, useState } from 'react'

import {
  formatApiError,
  uploadVolumeFolder,
} from '../../api/client'
import {
  VOLUME_UPLOAD_MAX_BYTES,
  VOLUME_UPLOAD_USER_QUOTA_BYTES,
  volumeUploadLimitMegabytes,
} from '../../constants/volumeUploadLimits'
import type { EnvVarRow, VolumeMountRow } from './runFormAdvanced'
import { createEmptyVolumeMountRow, folderTotalBytes } from './runFormAdvanced'
import {
  ContainersRunScalingFields,
  type ScalingPolicyRequest,
} from './ContainersRunScalingFields'

type ContainersRunAdvancedFieldsProps = {
  envRows: EnvVarRow[]
  onEnvRowsChange: (rows: EnvVarRow[]) => void
  volumeRows: VolumeMountRow[]
  onVolumeRowsChange: (rows: VolumeMountRow[]) => void
  startCommand: string
  onStartCommandChange: (value: string) => void
  scalingPolicy: ScalingPolicyRequest | null
  onScalingPolicyChange: (policy: ScalingPolicyRequest | null) => void
}

function formatBytes(totalBytes: number): string {
  if (totalBytes < 1024) {
    return `${totalBytes} B`
  }
  if (totalBytes < 1024 * 1024) {
    return `${(totalBytes / 1024).toFixed(1)} KB`
  }
  return `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`
}

export function ContainersRunAdvancedFields({
  envRows,
  onEnvRowsChange,
  volumeRows,
  onVolumeRowsChange,
  startCommand,
  onStartCommandChange,
  scalingPolicy,
  onScalingPolicyChange,
}: ContainersRunAdvancedFieldsProps) {
  const [expanded, setExpanded] = useState(false)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const [pickingRowIndex, setPickingRowIndex] = useState<number | null>(null)

  function updateEnvRow(index: number, patch: Partial<EnvVarRow>) {
    onEnvRowsChange(
      envRows.map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...patch } : row
      )
    )
  }

  function addEnvRow() {
    onEnvRowsChange([...envRows, { key: '', value: '' }])
  }

  function removeEnvRow(index: number) {
    const next = envRows.filter((_, rowIndex) => rowIndex !== index)
    onEnvRowsChange(next.length > 0 ? next : [{ key: '', value: '' }])
  }

  function updateVolumeRow(index: number, patch: Partial<VolumeMountRow>) {
    onVolumeRowsChange(
      volumeRows.map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...patch } : row
      )
    )
  }

  function addVolumeRow() {
    onVolumeRowsChange([...volumeRows, createEmptyVolumeMountRow()])
  }

  function removeVolumeRow(index: number) {
    const next = volumeRows.filter((_, rowIndex) => rowIndex !== index)
    onVolumeRowsChange(
      next.length > 0 ? next : [createEmptyVolumeMountRow()]
    )
  }

  function openFolderPicker(index: number) {
    setPickingRowIndex(index)
    folderInputRef.current?.click()
  }

  async function onFolderSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const fileList = event.target.files
    event.target.value = ''
    const rowIndex = pickingRowIndex
    setPickingRowIndex(null)
    if (!fileList || rowIndex === null) {
      return
    }

    const files = Array.from(fileList)
    if (files.length === 0) {
      updateVolumeRow(rowIndex, {
        error: 'Select a folder that contains at least one file.',
        uploading: false,
      })
      return
    }

    const totalBytes = folderTotalBytes(files)
    if (totalBytes > VOLUME_UPLOAD_MAX_BYTES) {
      updateVolumeRow(rowIndex, {
        error: `Folder exceeds the ${volumeUploadLimitMegabytes(VOLUME_UPLOAD_MAX_BYTES)} MB upload limit.`,
        uploading: false,
      })
      return
    }

    updateVolumeRow(rowIndex, {
      uploading: true,
      error: null,
      uploadId: null,
      folderName: null,
      totalBytes: null,
    })

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
      updateVolumeRow(rowIndex, {
        uploading: false,
        error: formatApiError(error),
      })
    }
  }

  return (
    <div className="containers-form__advanced">
      <input
        ref={folderInputRef}
        type="file"
        className="containers-form__folder-input"
        multiple
        onChange={(event) => void onFolderSelected(event)}
        {...{ webkitdirectory: '', directory: '' }}
        tabIndex={-1}
        aria-hidden="true"
      />
      <button
        type="button"
        className="btn btn--ghost containers-form__advanced-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((open) => !open)}
      >
        <span>Advanced options</span>
        <span
          className="containers-form__advanced-chevron"
          aria-hidden="true"
        >
          ›
        </span>
      </button>
      {expanded ? (
        <div className="containers-form__advanced-body">
          <p className="containers-form__label">Environment variables</p>
          <ul className="containers-env-list">
            {envRows.map((row, index) => (
              <li key={index} className="containers-env-list__row">
                <input
                  className="containers-form__input"
                  type="text"
                  placeholder="KEY"
                  aria-label={`Environment variable name ${index + 1}`}
                  value={row.key}
                  onChange={(event) =>
                    updateEnvRow(index, { key: event.target.value })
                  }
                />
                <input
                  className="containers-form__input"
                  type="text"
                  placeholder="value"
                  aria-label={`Environment variable value ${index + 1}`}
                  value={row.value}
                  onChange={(event) =>
                    updateEnvRow(index, { value: event.target.value })
                  }
                />
                <button
                  type="button"
                  className="btn btn--ghost btn--compact"
                  onClick={() => removeEnvRow(index)}
                  aria-label={`Remove environment variable ${index + 1}`}
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

          <p className="containers-form__label">Volumes (read-only)</p>
          <p className="containers-muted containers-form__hint">
            Choose a folder from your computer (up to{' '}
            {volumeUploadLimitMegabytes(VOLUME_UPLOAD_MAX_BYTES)} MB per folder,{' '}
            {volumeUploadLimitMegabytes(VOLUME_UPLOAD_USER_QUOTA_BYTES)} MB total per
            account). Mounts are read-only inside the container.
          </p>
          <ul className="containers-env-list">
            {volumeRows.map((row, index) => (
              <li key={index} className="containers-env-list__row containers-env-list__row--volume">
                <div className="containers-volume-row">
                  <button
                    type="button"
                    className="btn btn--ghost btn--compact"
                    disabled={row.uploading}
                    onClick={() => openFolderPicker(index)}
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
                      {row.totalBytes != null
                        ? ` (${formatBytes(row.totalBytes)})`
                        : ''}
                    </span>
                  ) : null}
                  <input
                    className="containers-form__input"
                    type="text"
                    placeholder="/path/in/container"
                    aria-label={`Volume target ${index + 1}`}
                    value={row.target}
                    onChange={(event) =>
                      updateVolumeRow(index, { target: event.target.value })
                    }
                  />
                  <button
                    type="button"
                    className="btn btn--ghost btn--compact"
                    onClick={() => removeVolumeRow(index)}
                    aria-label={`Remove volume ${index + 1}`}
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

          <label className="containers-form__label" htmlFor="start-command-input">
            Start command
          </label>
          <input
            id="start-command-input"
            className="containers-form__input"
            type="text"
            placeholder="Optional CMD override"
            value={startCommand}
            onChange={(event) => onStartCommandChange(event.target.value)}
          />
          <p className="containers-muted containers-form__hint">
            Overrides the container CMD when set.
          </p>

          <ContainersRunScalingFields
            scalingPolicy={scalingPolicy}
            onScalingPolicyChange={onScalingPolicyChange}
          />
        </div>
      ) : null}
    </div>
  )
}
