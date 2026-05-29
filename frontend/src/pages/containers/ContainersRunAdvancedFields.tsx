import { useState } from 'react'

import type { EnvVarRow } from './runFormAdvanced'

type ContainersRunAdvancedFieldsProps = {
  envRows: EnvVarRow[]
  onEnvRowsChange: (rows: EnvVarRow[]) => void
  startCommand: string
  onStartCommandChange: (value: string) => void
}

export function ContainersRunAdvancedFields({
  envRows,
  onEnvRowsChange,
  startCommand,
  onStartCommandChange,
}: ContainersRunAdvancedFieldsProps) {
  const [expanded, setExpanded] = useState(false)

  function updateRow(index: number, patch: Partial<EnvVarRow>) {
    onEnvRowsChange(
      envRows.map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...patch } : row
      )
    )
  }

  function addRow() {
    onEnvRowsChange([...envRows, { key: '', value: '' }])
  }

  function removeRow(index: number) {
    const next = envRows.filter((_, rowIndex) => rowIndex !== index)
    onEnvRowsChange(next.length > 0 ? next : [{ key: '', value: '' }])
  }

  return (
    <div className="containers-form__advanced">
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
                    updateRow(index, { key: event.target.value })
                  }
                />
                <input
                  className="containers-form__input"
                  type="text"
                  placeholder="value"
                  aria-label={`Environment variable value ${index + 1}`}
                  value={row.value}
                  onChange={(event) =>
                    updateRow(index, { value: event.target.value })
                  }
                />
                <button
                  type="button"
                  className="btn btn--ghost btn--compact"
                  onClick={() => removeRow(index)}
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
            onClick={addRow}
          >
            Add variable
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
        </div>
      ) : null}
    </div>
  )
}
