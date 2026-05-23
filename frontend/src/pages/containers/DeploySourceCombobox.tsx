import type { RefObject } from 'react'
import type { DeploySourceSuggestion } from '../../api/client'
import type { ImageRefCheckState } from './types'
import {
  selectionNeedsRegistryCheck,
  type DeploySourceSelection,
} from './deploySourceTypes'

type DeploySourceComboboxProps = {
  listboxId: string
  rootRef: RefObject<HTMLDivElement | null>
  displayValue: string
  selection: DeploySourceSelection | null
  suggestions: DeploySourceSuggestion[]
  listOpen: boolean
  searchLoading: boolean
  imageRefCheck: ImageRefCheckState
  onInputChange: (value: string) => void
  onInputFocus: () => void
  onPickSuggestion: (suggestion: DeploySourceSuggestion) => void
  onRequestImageCheck: (ref: string) => void
}

function groupLabel(kind: DeploySourceSuggestion['kind']): string {
  switch (kind) {
    case 'image':
      return 'Images'
    case 'git':
      return 'GitHub repositories'
    case 'dockerfile_template':
      return 'Dockerfiles'
  }
}

function suggestionKey(suggestion: DeploySourceSuggestion): string {
  switch (suggestion.kind) {
    case 'image':
      return `image:${suggestion.ref}`
    case 'git':
      return `git:${suggestion.url}`
    case 'dockerfile_template':
      return `dockerfile:${suggestion.id}`
  }
}

function suggestionOptionLabel(suggestion: DeploySourceSuggestion): string {
  switch (suggestion.kind) {
    case 'image':
      return suggestion.label
    case 'git':
      return suggestion.name
    case 'dockerfile_template':
      return suggestion.name
  }
}

export function DeploySourceCombobox({
  listboxId,
  rootRef,
  displayValue,
  selection,
  suggestions,
  listOpen,
  searchLoading,
  imageRefCheck,
  onInputChange,
  onInputFocus,
  onPickSuggestion,
  onRequestImageCheck,
}: DeploySourceComboboxProps) {
  const registryCheckEnabled = selectionNeedsRegistryCheck(selection)
  const groupedKinds: DeploySourceSuggestion['kind'][] = [
    'image',
    'git',
    'dockerfile_template',
  ]

  return (
    <>
      <div ref={rootRef} className="deploy-source-combobox">
        <input
          id="deploy-source-input"
          className="containers-form__input"
          type="text"
          role="combobox"
          aria-expanded={listOpen}
          aria-controls={listboxId}
          aria-autocomplete="list"
          autoComplete="off"
          placeholder="Search images, GitHub repos, or Dockerfiles…"
          value={displayValue}
          onChange={(event) => onInputChange(event.target.value)}
          onFocus={onInputFocus}
          onBlur={() => {
            if (selection?.kind === 'image') {
              void onRequestImageCheck(selection.ref)
            }
          }}
          aria-label="Deploy source"
          aria-invalid={
            registryCheckEnabled &&
            imageRefCheck.status === 'unavailable' &&
            !imageRefCheck.canAttemptDeploy
              ? true
              : undefined
          }
          aria-describedby={
            registryCheckEnabled && imageRefCheck.status !== 'idle'
              ? 'deploy-source-status'
              : undefined
          }
        />
        {listOpen ? (
          <ul
            id={listboxId}
            className="deploy-source-combobox__list"
            role="listbox"
          >
            {searchLoading && suggestions.length === 0 ? (
              <li className="deploy-source-combobox__empty" role="presentation">
                Searching…
              </li>
            ) : null}
            {!searchLoading && suggestions.length === 0 ? (
              <li className="deploy-source-combobox__empty" role="presentation">
                No matches. Try another search.
              </li>
            ) : null}
            {groupedKinds.map((kind) => {
              const rows = suggestions.filter((row) => row.kind === kind)
              if (rows.length === 0) {
                return null
              }
              return (
                <li key={kind} role="presentation">
                  <span className="deploy-source-combobox__group">
                    {groupLabel(kind)}
                  </span>
                  <ul role="group">
                    {rows.map((row) => (
                      <li key={suggestionKey(row)} role="presentation">
                        <button
                          type="button"
                          className="deploy-source-combobox__option"
                          role="option"
                          onMouseDown={(event) => event.preventDefault()}
                          onClick={() => onPickSuggestion(row)}
                        >
                          {suggestionOptionLabel(row)}
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              )
            })}
          </ul>
        ) : null}
      </div>
      {registryCheckEnabled && imageRefCheck.status === 'checking' ? (
        <p
          id="deploy-source-status"
          className="containers-source-check containers-source-check--muted"
        >
          Checking registry…
        </p>
      ) : null}
      {registryCheckEnabled && imageRefCheck.status === 'ok' ? (
        <p
          id="deploy-source-status"
          className="containers-source-check containers-source-check--ok"
        >
          Image reference found.
        </p>
      ) : null}
      {registryCheckEnabled && imageRefCheck.status === 'unavailable' ? (
        <p
          id="deploy-source-status"
          className={
            imageRefCheck.canAttemptDeploy
              ? 'containers-source-check containers-source-check--warn'
              : 'containers-source-check containers-source-check--err'
          }
          role="alert"
        >
          {imageRefCheck.canAttemptDeploy
            ? 'Registry did not confirm this image (you may need registry access). You can still try Build.'
            : 'Image not found in the registry.'}
        </p>
      ) : null}
      {registryCheckEnabled && imageRefCheck.status === 'error' ? (
        <p
          id="deploy-source-status"
          className="containers-source-check containers-source-check--warn"
          role="alert"
        >
          Could not verify image: {imageRefCheck.detail}
        </p>
      ) : null}
    </>
  )
}
