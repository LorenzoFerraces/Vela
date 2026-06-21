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

/**
 * Produce a human-readable group label for a deploy source suggestion kind.
 *
 * @param kind - The suggestion kind; one of `image`, `git`, or `dockerfile_template`
 * @returns The corresponding group label: `'Images'` for `image`, `'GitHub repositories'` for `git`, or `'Dockerfiles'` for `dockerfile_template`
 */
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

/**
 * Produces a stable key string for a deploy-source suggestion suitable for use as a React `key`.
 *
 * @param suggestion - The suggestion to create a key for
 * @returns A key string formatted as `image:<ref>`, `git:<url>`, or `dockerfile:<id>` depending on the suggestion kind
 */
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

/**
 * Get the display label for a deploy-source suggestion.
 *
 * @param suggestion - The suggestion object to derive the option label from
 * @returns The text to show for the suggestion: for `image` suggestions the suggestion's `label`, for `git` and `dockerfile_template` suggestions the suggestion's `name`
 */
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

const SKELETON_GROUP_WIDTHS = ['4.5rem', '5.75rem'] as const
const SKELETON_OPTION_WIDTHS = ['92%', '78%', '85%'] as const

/**
 * Renders a placeholder skeleton list of grouped suggestion rows displayed while suggestions are loading.
 *
 * @returns A fragment containing placeholder group headers, option rows, and a status item that reads "Searching…".
 */
function DeploySourceSuggestionsSkeleton() {
  return (
  <>
    {SKELETON_GROUP_WIDTHS.map((groupWidth, groupIndex) => (
      <li key={groupIndex} role="presentation">
        <span
          className="deploy-source-combobox__skeleton deploy-source-combobox__skeleton--group"
          style={{ width: groupWidth }}
          aria-hidden="true"
        />
        <ul role="group" aria-hidden="true">
          {SKELETON_OPTION_WIDTHS.map((optionWidth, optionIndex) => (
            <li key={optionIndex} role="presentation">
              <span
                className="deploy-source-combobox__skeleton deploy-source-combobox__skeleton--option"
                style={{ width: optionWidth }}
              />
            </li>
          ))}
        </ul>
      </li>
    ))}
    <li className="deploy-source-combobox__status" role="status" aria-live="polite">
      Searching…
    </li>
  </>
  )
}

/**
 * Render a deploy-source combobox for selecting images, GitHub repositories, or Dockerfiles.
 *
 * Renders a controlled text input with an optional grouped listbox of suggestions, accessibility attributes,
 * and conditional registry-check status messages for image selections.
 *
 * @param listboxId - DOM id used for the suggestions listbox element
 * @param rootRef - RefObject for the combobox root element
 * @param displayValue - Current input string shown in the text field
 * @param selection - Currently selected suggestion (if any)
 * @param suggestions - Array of suggestions to show in the listbox
 * @param listOpen - Whether the suggestions listbox is visible
 * @param searchLoading - Whether suggestion search is in progress (shows skeleton when true)
 * @param imageRefCheck - State of the image registry check for the current selection
 * @param onInputChange - Called with the new input string when the text changes
 * @param onInputFocus - Called when the input receives focus
 * @param onPickSuggestion - Called with a suggestion when the user selects it
 * @param onRequestImageCheck - Requests a registry check for a given image reference
 * @returns The rendered combobox React element
 */
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
            aria-busy={searchLoading}
          >
            {searchLoading ? (
              <DeploySourceSuggestionsSkeleton />
            ) : null}
            {!searchLoading && suggestions.length === 0 ? (
              <li className="deploy-source-combobox__empty" role="presentation">
                No matches. Try another search.
              </li>
            ) : null}
            {!searchLoading
              ? groupedKinds.map((kind) => {
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
            })
              : null}
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
