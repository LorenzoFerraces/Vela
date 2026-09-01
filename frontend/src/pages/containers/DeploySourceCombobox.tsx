import { useEffect, useMemo, useState } from 'react'
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
  pastedGithubRepoPending?: boolean
  pastedGithubHint?: string | null
  imageRefCheck: ImageRefCheckState
  onInputChange: (value: string) => void
  onInputFocus: () => void
  onPickSuggestion: (suggestion: DeploySourceSuggestion) => void
  onRequestImageCheck: (ref: string) => void
  onCommitPastedGithubRepo?: () => void
  onListClose: () => void
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

function isOptionSelected(
  selection: DeploySourceSelection | null,
  suggestion: DeploySourceSuggestion,
): boolean {
  if (!selection) {
    return false
  }
  switch (suggestion.kind) {
    case 'image':
      return selection.kind === 'image' && selection.ref === suggestion.ref
    case 'git':
      return selection.kind === 'git' && selection.url === suggestion.url
    case 'dockerfile_template':
      return (
        selection.kind === 'dockerfile_template' &&
        selection.templateId === suggestion.id
      )
  }
}

const GROUPED_KINDS: DeploySourceSuggestion['kind'][] = [
  'image',
  'git',
  'dockerfile_template',
]

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
  pastedGithubRepoPending = false,
  pastedGithubHint = null,
  imageRefCheck,
  onInputChange,
  onInputFocus,
  onPickSuggestion,
  onRequestImageCheck,
  onCommitPastedGithubRepo,
  onListClose,
}: DeploySourceComboboxProps) {
  const registryCheckEnabled = selectionNeedsRegistryCheck(selection)
  const options = useMemo(() => {
    const rowsByKind: Record<
      DeploySourceSuggestion['kind'],
      DeploySourceSuggestion[]
    > = {
      image: [],
      git: [],
      dockerfile_template: [],
    }
    for (const row of suggestions) {
      rowsByKind[row.kind].push(row)
    }
    return GROUPED_KINDS.flatMap((kind) => rowsByKind[kind])
  }, [suggestions])
  const [activeIndex, setActiveIndex] = useState(-1)
  const activeOptionIndex =
    activeIndex >= 0 ? Math.min(activeIndex, options.length - 1) : -1

  useEffect(() => {
    if (activeOptionIndex < 0) {
      return
    }
    const option = options[activeOptionIndex]
    if (!option) {
      return
    }
    document
      .getElementById(`deploy-source-option-${suggestionKey(option)}`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [activeOptionIndex, options])

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (listOpen && options.length > 0) {
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setActiveIndex((index) => Math.min(index + 1, options.length - 1))
        return
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setActiveIndex((index) =>
          index < 0 ? options.length - 1 : index - 1,
        )
        return
      }
      if (event.key === 'Home') {
        event.preventDefault()
        setActiveIndex(0)
        return
      }
      if (event.key === 'End') {
        event.preventDefault()
        setActiveIndex(options.length - 1)
        return
      }
    }
    if (event.key === 'Escape' && listOpen) {
      event.preventDefault()
      onListClose()
      return
    }
    if (event.key === 'Enter' && listOpen && activeOptionIndex >= 0) {
      event.preventDefault()
      setActiveIndex(-1)
      onPickSuggestion(options[activeOptionIndex])
      return
    }
    if (
      event.key === 'Enter' &&
      listOpen &&
      pastedGithubRepoPending &&
      onCommitPastedGithubRepo
    ) {
      event.preventDefault()
      onCommitPastedGithubRepo()
    }
  }

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
          aria-activedescendant={
            activeOptionIndex >= 0
              ? `deploy-source-option-${suggestionKey(options[activeOptionIndex])}`
              : undefined
          }
          placeholder="Search images, GitHub repos, or Dockerfiles…"
          value={displayValue}
          onChange={(event) => {
            setActiveIndex(-1)
            onInputChange(event.target.value)
          }}
          onFocus={onInputFocus}
          onKeyDown={handleKeyDown}
          onBlur={() => {
            onCommitPastedGithubRepo?.()
            if (selection?.kind === 'image') {
              void onRequestImageCheck(selection.ref)
            }
          }}
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
                {pastedGithubHint
                  ? pastedGithubHint
                  : pastedGithubRepoPending
                    ? 'Repository not found or you do not have access. Connect GitHub in Settings if this is a private repo.'
                    : 'No matches. Try another search.'}
              </li>
            ) : null}
            {!searchLoading
              ? GROUPED_KINDS.map((kind) => {
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
                        <div
                          id={`deploy-source-option-${suggestionKey(row)}`}
                          className="deploy-source-combobox__option"
                          role="option"
                          aria-selected={isOptionSelected(selection, row)}
                          onMouseDown={(event) => event.preventDefault()}
                          onClick={() => onPickSuggestion(row)}
                        >
                          {suggestionOptionLabel(row)}
                        </div>
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
          role="status"
        >
          Checking registry…
        </p>
      ) : null}
      {registryCheckEnabled && imageRefCheck.status === 'ok' ? (
        <p
          id="deploy-source-status"
          className="containers-source-check containers-source-check--ok"
          role="status"
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
