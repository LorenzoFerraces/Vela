import { useCallback, useEffect, useId, useRef, useState } from 'react'
import {
  getDeploySourceSuggestions,
  type DeploySourceSuggestion,
} from '../../api/client'
import type { DeploySourceSelection } from './deploySourceTypes'
import {
  deploySourceLabel,
  findPastedGithubRepoSuggestion,
  queryLooksLikeGithubRepoUrl,
} from './deploySourceTypes'

const SEARCH_DEBOUNCE_MS = 320
const SEARCH_LIMIT = 22

/**
 * Manages input state, debounced remote suggestions, selection, and list visibility for a deploy-source picker.
 *
 * The hook maintains the input `query`, the current `selection`, fetched `suggestions`, whether the suggestion list is open (`listOpen`),
 * and a `searchLoading` flag while debounced suggestion requests are in flight. It provides handlers to update/clear selection,
 * open the list on focus or input, and apply a selected suggestion. Outside clicks close the suggestion list.
 *
 * @returns An object exposing state, refs, and action handlers:
 * - `listboxId` — stable id for the suggestions listbox.
 * - `rootRef` — ref for the hook's root container element (used to detect outside clicks).
 * - `query` — current raw input string.
 * - `selection` — currently selected `DeploySourceSelection` or `null`.
 * - `suggestions` — array of `DeploySourceSuggestion` returned from the API.
 * - `listOpen` — whether the suggestions list is open.
 * - `searchLoading` — whether a debounced search request is in progress.
 * - `displayValue` — string shown in the input (selection label if selected, otherwise `query`).
 * - `setSelection` — setter to programmatically set the current selection.
 * - `applySuggestion` — apply a `DeploySourceSuggestion` as the active selection and close the list.
 * - `clearSelection` — clear the selection, query, and suggestions.
 * - `onInputChange` — handler to call when the input value changes (clears selection, updates query, opens list).
 * - `onInputFocus` — handler to call when the input receives focus (opens list).
 * - `setListOpen` — setter to explicitly open or close the suggestions list.
 */
export function useDeploySourceSelection() {
  const listboxId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [selection, setSelection] = useState<DeploySourceSelection | null>(null)
  const [suggestions, setSuggestions] = useState<DeploySourceSuggestion[]>([])
  const [listOpen, setListOpen] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)
  const [pastedGithubHint, setPastedGithubHint] = useState<string | null>(null)
  const searchGenerationRef = useRef(0)
  const lastFetchedQueryRef = useRef<string | null>(null)

  const displayValue = selection ? deploySourceLabel(selection) : query

  const refreshSuggestions = useCallback(async (searchQuery: string, generation: number) => {
    try {
      const result = await getDeploySourceSuggestions(searchQuery, {
        limit: SEARCH_LIMIT,
      })
      if (generation !== searchGenerationRef.current) {
        return
      }
      setSuggestions(result.suggestions)
      setPastedGithubHint(result.pasted_github_hint)
      lastFetchedQueryRef.current = searchQuery
    } catch {
      if (generation !== searchGenerationRef.current) {
        return
      }
      setSuggestions([])
      setPastedGithubHint(null)
      lastFetchedQueryRef.current = searchQuery
    } finally {
      if (generation === searchGenerationRef.current) {
        setSearchLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    if (!listOpen) {
      setSearchLoading(false)
      return
    }

    if (lastFetchedQueryRef.current === query) {
      setSearchLoading(false)
      return
    }

    searchGenerationRef.current += 1
    const generation = searchGenerationRef.current
    setSearchLoading(true)

    const timer = window.setTimeout(() => {
      void refreshSuggestions(query, generation)
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [query, listOpen, refreshSuggestions])

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      const root = rootRef.current
      if (root && !root.contains(event.target as Node)) {
        setListOpen(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [])

  function applySuggestion(suggestion: DeploySourceSuggestion) {
    switch (suggestion.kind) {
      case 'image':
        setSelection({
          kind: 'image',
          ref: suggestion.ref,
          label: suggestion.label,
        })
        break
      case 'git':
        setSelection({
          kind: 'git',
          url: suggestion.url,
          name: suggestion.name,
          defaultBranch: suggestion.default_branch,
        })
        break
      case 'dockerfile_template':
        setSelection({
          kind: 'dockerfile_template',
          templateId: suggestion.id,
          name: suggestion.name,
        })
        break
    }
    setQuery('')
    setListOpen(false)
    lastFetchedQueryRef.current = null
  }

  function tryCommitPastedGithubRepo(): DeploySourceSuggestion | null {
    if (selection) {
      return null
    }
    return findPastedGithubRepoSuggestion(query, suggestions)
  }

  function clearSelection() {
    setSelection(null)
    setQuery('')
    setSuggestions([])
    setPastedGithubHint(null)
    lastFetchedQueryRef.current = null
  }

  function onInputChange(nextRaw: string) {
    setSelection(null)
    setQuery(nextRaw)
    setPastedGithubHint(null)
    setListOpen(true)
  }

  function onInputFocus() {
    setListOpen(true)
  }

  const pastedGithubRepoPending =
    !selection && queryLooksLikeGithubRepoUrl(query) && !searchLoading

  return {
    listboxId,
    rootRef,
    query,
    selection,
    suggestions,
    listOpen,
    searchLoading,
    pastedGithubRepoPending,
    pastedGithubHint,
    displayValue,
    setSelection,
    applySuggestion,
    tryCommitPastedGithubRepo,
    clearSelection,
    onInputChange,
    onInputFocus,
    setListOpen,
  }
}
