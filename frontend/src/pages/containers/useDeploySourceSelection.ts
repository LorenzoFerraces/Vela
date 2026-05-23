import { useCallback, useEffect, useId, useRef, useState } from 'react'
import {
  getDeploySourceSuggestions,
  type DeploySourceSuggestion,
} from '../../api/client'
import type { DeploySourceSelection } from './deploySourceTypes'
import { deploySourceLabel } from './deploySourceTypes'

const SEARCH_DEBOUNCE_MS = 320
const SEARCH_LIMIT = 22

export function useDeploySourceSelection() {
  const listboxId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [selection, setSelection] = useState<DeploySourceSelection | null>(null)
  const [suggestions, setSuggestions] = useState<DeploySourceSuggestion[]>([])
  const [listOpen, setListOpen] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)

  const displayValue = selection ? deploySourceLabel(selection) : query

  const refreshSuggestions = useCallback(async (searchQuery: string) => {
    setSearchLoading(true)
    try {
      const rows = await getDeploySourceSuggestions(searchQuery, {
        limit: SEARCH_LIMIT,
      })
      setSuggestions(rows)
    } catch {
      setSuggestions([])
    } finally {
      setSearchLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!listOpen) {
      return
    }
    const timer = window.setTimeout(() => {
      void refreshSuggestions(query)
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
  }

  function clearSelection() {
    setSelection(null)
    setQuery('')
    setSuggestions([])
  }

  function onInputChange(nextRaw: string) {
    setSelection(null)
    setQuery(nextRaw)
    setListOpen(true)
  }

  function onInputFocus() {
    setListOpen(true)
    void refreshSuggestions(query)
  }

  return {
    listboxId,
    rootRef,
    query,
    selection,
    suggestions,
    listOpen,
    searchLoading,
    displayValue,
    setSelection,
    applySuggestion,
    clearSelection,
    onInputChange,
    onInputFocus,
    setListOpen,
  }
}
