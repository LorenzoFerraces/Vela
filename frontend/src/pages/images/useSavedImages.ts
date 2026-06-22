import { useCallback, useEffect, useState } from 'react'
import {
  formatApiError,
} from '../../api/client'
import type { ImagesBanner } from './types'

export function useSavedImages(
  reportBanner: (banner: ImagesBanner) => void
) {
  const [listLoading, setListLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setListLoading(true)
    try {
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
      await refresh()
      reportBanner({ tone: 'ok', text: 'Image reference removed.' })
    } catch (error) {
      reportBanner({ tone: 'err', text: formatApiError(error) })
    } finally {
      setBusy(false)
    }
  }

  return {
    listLoading,
    busy,
    refresh,
    addImage,
    removeImage
  }
}
