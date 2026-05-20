import { useCallback, useEffect, useState } from 'react'
import {
  createDockerfileTemplate,
  deleteDockerfileTemplate,
  formatApiError,
  listDockerfileTemplates,
  updateDockerfileTemplate,
  type DockerfileTemplate,
} from '../../api/client'
import type { ImagesBanner } from './types'

export function useDockerfileTemplates(
  reportBanner: (banner: ImagesBanner) => void
) {
  const [rows, setRows] = useState<DockerfileTemplate[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editContents, setEditContents] = useState('')

  const refresh = useCallback(async () => {
    setListLoading(true)
    try {
      const data = await listDockerfileTemplates()
      setRows(data)
    } catch (error) {
      reportBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setListLoading(false)
    }
  }, [reportBanner])

  useEffect(() => {
    void refresh()
  }, [refresh])

  function selectTemplate(template: DockerfileTemplate) {
    setSelectedId(template.id)
    setEditName(template.name)
    setEditContents(template.contents)
  }

  function clearSelection() {
    setSelectedId(null)
    setEditName('')
    setEditContents('')
  }

  async function createTemplate(name: string, contents: string) {
    const trimmedName = name.trim()
    const trimmedContents = contents.trim()
    if (!trimmedName || !trimmedContents) {
      reportBanner({
        tone: 'err',
        text: 'Name and Dockerfile contents are required.',
      })
      return false
    }
    setBusy(true)
    reportBanner(null)
    try {
      const created = await createDockerfileTemplate({
        name: trimmedName,
        contents: trimmedContents,
      })
      await refresh()
      selectTemplate(created)
      reportBanner({ tone: 'ok', text: `Created template ${trimmedName}.` })
      return true
    } catch (error) {
      reportBanner({ tone: 'err', text: formatApiError(error) })
      return false
    } finally {
      setBusy(false)
    }
  }

  async function saveSelected() {
    if (!selectedId) {
      reportBanner({ tone: 'err', text: 'Select a template to save.' })
      return
    }
    setBusy(true)
    reportBanner(null)
    try {
      const updated = await updateDockerfileTemplate(selectedId, {
        name: editName.trim(),
        contents: editContents,
      })
      await refresh()
      selectTemplate(updated)
      reportBanner({ tone: 'ok', text: 'Dockerfile template saved.' })
    } catch (error) {
      reportBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  async function removeTemplate(templateId: string) {
    setBusy(true)
    reportBanner(null)
    try {
      await deleteDockerfileTemplate(templateId)
      if (selectedId === templateId) {
        clearSelection()
      }
      await refresh()
      reportBanner({ tone: 'ok', text: 'Dockerfile template deleted.' })
    } catch (error) {
      reportBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  return {
    rows,
    listLoading,
    busy,
    selectedId,
    editName,
    editContents,
    setEditName,
    setEditContents,
    refresh,
    selectTemplate,
    clearSelection,
    createTemplate,
    saveSelected,
    removeTemplate,
  }
}
