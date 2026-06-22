import { useCallback, useEffect, useState } from 'react'
import {
  createSavedImage,
  deleteSavedImage,
  formatApiError,
  listSavedImages,
  type SavedImage,
} from '../../api/client'
import type { ImagesBanner } from './types'

export function useSavedImages(
  reportBanner: (banner: ImagesBanner) => void
) {
  const [rows, setRows] = useState<SavedImage[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setListLoading(true)
    try {
      const data = await listSavedImages()
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

  async function addImage(ref: string) {
    const trimmed = ref.trim()
    if (!trimmed) {
      reportBanner({ tone: 'err', text: 'Enter an image reference.' })
      return false
    }
    setBusy(true)
    reportBanner(null)
    try {
      await createSavedImage(trimmed)
      await refresh()
      reportBanner({ tone: 'ok', text: `Saved ${trimmed}.` })
      return true
    } catch (error) {
      reportBanner({ tone: 'err', text: formatApiError(error) })
      return false
    } finally {
      setBusy(false)
    }
  }

  async function removeImage(imageId: string) {
    setBusy(true)
    reportBanner(null)
    try {
      await deleteSavedImage(imageId)
      await refresh()
      reportBanner({ tone: 'ok', text: 'Image reference removed.' })
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
    refresh,
    addImage,
    removeImage,
  }
}
