import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ContainerStatus } from '../../api/client'
import {
  fetchContainerLogs,
  formatApiError,
  openContainerLogWebSocket,
} from '../../api/client'

const ERROR_LINE_PATTERN = /\b(error|exception|fatal|traceback)\b/i

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

  const refreshSnapshot = useCallback(async () => {
    try {
      const snapshot = await fetchContainerLogs(containerId, { tail: 500 })
      setLogText(snapshot)
      setErrorText(null)
    } catch (error) {
      setErrorText(formatApiError(error))
    }
  }, [containerId])

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

    let websocket: WebSocket
    try {
      websocket = openContainerLogWebSocket(containerId, {
        tail: 400,
        follow: true,
      })
    } catch (error) {
      queueMicrotask(() => {
        setStreamStatus('err')
        setErrorText(formatApiError(error))
      })
      return
    }
    websocket.binaryType = 'arraybuffer'
    websocket.onopen = () => {
      queueMicrotask(() => {
        setStreamStatus('live')
      })
    }
    websocket.onmessage = (event) => {
      const payload = event.data
      const chunk =
        payload instanceof ArrayBuffer
          ? new Uint8Array(payload)
          : typeof payload === 'string'
            ? new TextEncoder().encode(payload)
            : new Uint8Array()
      if (chunk.length === 0) {
        return
      }
      const piece = decoderRef.current.decode(chunk, { stream: true })
      setLogText((previous) => previous + piece)
    }
    websocket.onerror = () => {
      queueMicrotask(() => {
        setErrorText('Log stream connection failed.')
        setStreamStatus('err')
      })
    }
    websocket.onclose = () => {
      queueMicrotask(() => {
        setStreamStatus((previous) => (previous === 'err' ? previous : 'ended'))
      })
    }
    return () => {
      websocket.onopen = null
      websocket.onmessage = null
      websocket.onerror = null
      websocket.onclose = null
      websocket.close()
    }
  }, [containerId, isActive, isRunning])

  const lines = useMemo(() => logText.split('\n'), [logText])

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
        {lines.map((line, index) => {
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
