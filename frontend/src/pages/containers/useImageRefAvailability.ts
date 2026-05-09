import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { formatApiError, getImageAvailability } from '../../api/client'
import { IMAGE_REF_CHECK_DEBOUNCE_MS } from './constants'
import type { ImageRefCheckState } from './types'
import { sourceLooksLikeGitUrl } from './sourceKind'

export function useImageRefAvailability(source: string) {
  const sourceTrimmedRef = useRef('')

  useLayoutEffect(() => {
    sourceTrimmedRef.current = source.trim()
  }, [source])

  const [imageRefCheck, setImageRefCheck] = useState<ImageRefCheckState>({
    status: 'idle',
  })

  const runImageRefAvailabilityCheck = useCallback(async (ref: string) => {
    setImageRefCheck({ status: 'checking' })
    try {
      const result = await getImageAvailability(ref)
      if (sourceTrimmedRef.current !== ref) {
        return
      }
      if (!result.checked) {
        setImageRefCheck({ status: 'idle' })
        return
      }
      if (result.available) {
        setImageRefCheck({ status: 'ok', ref: result.ref })
      } else {
        setImageRefCheck({
          status: 'unavailable',
          ref: result.ref,
          canAttemptDeploy: result.can_attempt_deploy === true,
        })
      }
    } catch (error) {
      if (sourceTrimmedRef.current !== ref) {
        return
      }
      setImageRefCheck({
        status: 'error',
        detail: formatApiError(error),
      })
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const trimmed = source.trim()
    if (!trimmed || sourceLooksLikeGitUrl(trimmed)) {
      queueMicrotask(() => {
        if (cancelled) return
        setImageRefCheck({ status: 'idle' })
      })
      return () => {
        cancelled = true
      }
    }
    const handle = window.setTimeout(() => {
      if (cancelled) return
      void runImageRefAvailabilityCheck(trimmed)
    }, IMAGE_REF_CHECK_DEBOUNCE_MS)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
    }
  }, [source, runImageRefAvailabilityCheck])

  return {
    imageRefCheck,
    setImageRefCheck,
    runImageRefAvailabilityCheck,
  }
}
