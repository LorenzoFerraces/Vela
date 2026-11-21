import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ContainerStatus } from '../../api/client'
import {
  fetchContainerLogs,
  formatApiError,
  openContainerLogWebSocket,
} from '../../api/client'

const ERROR_LINE_PATTERN = /\b(error|exception|fatal|traceback)\b/i
const MAX_LOG_BUFFER_CHARS = 256_000
const RENDERED_LINE_LIMIT = 1500
const textEncoder = new TextEncoder()

function appendWithLimit(previous: string, piece: string): string {
  const next = previous + piece
  if (next.length <= MAX_LOG_BUFFER_CHARS) {
    return next
  }
  return next.slice(next.length - MAX_LOG_BUFFER_CHARS)
}

type ContainerLogPanelProps = {
  containerId: string
  isActive: boolean
  workloadStatus: ContainerStatus
}

export function ContainerLogPanel({
  containerId,
  isActive,
  workloadStatus,
}: ContainerLogPanelProps) {
  const isRunning = workloadStatus === 'running'
  const [logText, setLogText] = useState('')
  const [streamStatus, setStreamStatus] = useState<
    'connecting' | 'live' | 'ended' | 'err'
  >('connecting')
  const [errorText, setErrorText] = useState<string | null>(null)
  const [highlightErrors, setHighlightErrors] = useState(false)
  const decoderRef = useRef(new TextDecoder())
  const pendingRef = useRef('')
  const flushScheduledRef = useRef(false)
  const frameRef = useRef<number | null>(null)

  const refreshSnapshot = useCallback(async () => {
    try {
      const snapshot = await fetchContainerLogs(containerId, { tail: 500 })
      setLogText(snapshot.slice(-MAX_LOG_BUFFER_CHARS))
      setErrorText(null)
    } catch (error) {
      setErrorText(formatApiError(error))
    }
  }, [containerId])

  const flushPending = useCallback(() => {
    if (!flushScheduledRef.current) {
      return
    }
    flushScheduledRef.current = false
    const pending = pendingRef.current
    if (pending === '') {
      return
    }
    pendingRef.current = ''
    setLogText((previous) => appendWithLimit(previous, pending))
  }, [])

  // ponytail: rAF pauses in background tabs; pending buffer capped at MAX_LOG_BUFFER_CHARS
  const scheduleFlush = useCallback(() => {
    if (flushScheduledRef.current) {
      return
    }
    flushScheduledRef.current = true
    frameRef.current = requestAnimationFrame(() => {
      flushPending()
    })
  }, [flushPending])

  useEffect(() => {
    if (!isActive || isRunning) {
      return
    }
    void refreshSnapshot()
  }, [isActive, isRunning, containerId, refreshSnapshot])

  useEffect(() => {
    if (!isActive || !isRunning) {
      return
    }

    decoderRef.current = new TextDecoder()
    setLogText('')
    setStreamStatus('connecting')
    setErrorText(null)

    let disposed = false
    let websocket: WebSocket | null = null

    void (async () => {
      let socket: WebSocket
      try {
        socket = await openContainerLogWebSocket(containerId, {
          tail: 400,
          follow: true,
        })
      } catch (error) {
        if (!disposed) {
          queueMicrotask(() => {
            if (!disposed) {
              setStreamStatus('err')
              setErrorText(formatApiError(error))
            }
          })
        }
        return
      }
      if (disposed) {
        socket.close()
        return
      }
      websocket = socket
      socket.binaryType = 'arraybuffer'
      socket.onopen = () => {
        queueMicrotask(() => {
          if (!disposed) setStreamStatus('live')
        })
      }
      socket.onmessage = (event) => {
        if (disposed) return
        const payload = event.data
        const chunk =
          payload instanceof ArrayBuffer
            ? new Uint8Array(payload)
            : typeof payload === 'string'
                ? textEncoder.encode(payload)
               : new Uint8Array()
        if (chunk.length === 0) {
          return
        }
        const piece = decoderRef.current.decode(chunk, { stream: true })
        if (piece === '') {
          return
        }
        pendingRef.current = appendWithLimit(pendingRef.current, piece)
        scheduleFlush()
      }
      socket.onerror = () => {
        queueMicrotask(() => {
          if (disposed) return
          setErrorText('Log stream connection failed.')
          setStreamStatus('err')
        })
      }
      socket.onclose = () => {
        queueMicrotask(() => {
          if (disposed) return
          flushPending()
          setStreamStatus((previous) => (previous === 'err' ? previous : 'ended'))
        })
      }
    })()

    return () => {
      disposed = true
      if (websocket) {
        websocket.onopen = null
        websocket.onmessage = null
        websocket.onerror = null
        websocket.onclose = null
        websocket.close()
      }
      if (frameRef.current !== null) {
        cancelAnimationFrame(frameRef.current)
        frameRef.current = null
      }
      flushPending()
    }
  }, [containerId, isActive, isRunning, flushPending, scheduleFlush])

  const { visibleLines, hasHiddenLines } = useMemo(() => {
    const all = logText.split('\n')
    if (all.length <= RENDERED_LINE_LIMIT) {
      return { visibleLines: all, hasHiddenLines: false }
    }
    return {
      visibleLines: all.slice(all.length - RENDERED_LINE_LIMIT),
      hasHiddenLines: true,
    }
  }, [logText])

  return (
    <div className="workloads-log-panel">
      <div className="workloads-log-panel__toolbar">
        <span className="workloads-log-panel__status" role="status">
          {!isRunning
            ? 'Stream paused'
            : streamStatus === 'connecting'
              ? 'Connecting…'
              : streamStatus === 'live'
                ? 'Live'
                : streamStatus === 'ended'
                  ? 'Stream ended'
                  : 'Error'}
        </span>
        <label className="workloads-log-panel__toggle">
          <input
            type="checkbox"
            checked={highlightErrors}
            onChange={(event) => setHighlightErrors(event.target.checked)}
          />
          Highlight error lines
        </label>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => void refreshSnapshot()}
        >
          Refresh snapshot
        </button>
      </div>
      {errorText ? (
        <p className="workloads-log-panel__error" role="alert">
          {errorText}
        </p>
      ) : null}
      <pre
        className="workloads-log-panel__pre"
        tabIndex={0}
        aria-label="Container log output"
      >
        {hasHiddenLines ? (
          <span className="workloads-log-panel__line">
            Showing last {RENDERED_LINE_LIMIT} lines…
          </span>
        ) : null}
        {visibleLines.map((line, index) => {
          const key = `${index}-${line.slice(0, 24)}`
          if (highlightErrors && ERROR_LINE_PATTERN.test(line)) {
            return (
              <span
                key={key}
                className="workloads-log-panel__line workloads-log-panel__line--warn"
              >
                {line}
                {'\n'}
              </span>
            )
          }
          return (
            <span key={key} className="workloads-log-panel__line">
              {line}
              {'\n'}
            </span>
          )
        })}
      </pre>
    </div>
  )
}
