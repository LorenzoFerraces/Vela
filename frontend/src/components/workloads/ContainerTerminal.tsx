import { useEffect, useRef } from 'react'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import 'xterm/css/xterm.css'
import { openContainerExecWebSocket, type ExecWebSocketHandle } from '../../api/client'

interface ContainerTerminalProps {
  containerId: string
  onClose: () => void
}

export function ContainerTerminal({ containerId, onClose }: ContainerTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let disposed = false

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", Menlo, monospace',
      theme: { background: '#120e1e', foreground: '#e9e4f2' },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)

    let resourcesDisposed = false
    const disposeResources = () => {
      if (resourcesDisposed) return
      resourcesDisposed = true
      term.dispose()
      fit.dispose()
    }

    const container = containerRef.current
    if (!container) {
      disposeResources()
      return
    }
    term.open(container)
    fit.fit()

    let execWs: ExecWebSocketHandle | null = null
    let resizeFrame = 0
    let resizeObserver: ResizeObserver | null = null

    void (async () => {
      let socket: ExecWebSocketHandle
      try {
        socket = await openContainerExecWebSocket(
          containerId,
          () => {
            socket.send(JSON.stringify({ cols: term.cols, rows: term.rows }))
          },
          (data) => { if (!disposed) term.write(data) },
          () => { if (!disposed) term.write('\r\n\x1b[31m[connection closed]\x1b[0m\r\n') },
          () => { if (!disposed) term.write('\r\n\x1b[31m[connection error]\x1b[0m\r\n') },
        )
      } catch {
        if (!disposed) disposeResources()
        return
      }
      if (disposed) {
        socket.dispose()
        return
      }
      execWs = socket
      term.onData((inputData) => socket.send(inputData))

      resizeObserver = new ResizeObserver(() => {
        if (resizeFrame) return
        resizeFrame = requestAnimationFrame(() => {
          resizeFrame = 0
          if (disposed) return
          fit.fit()
          socket.send(JSON.stringify({ resize: { cols: term.cols, rows: term.rows } }))
        })
      })
      resizeObserver.observe(container)
    })()

    return () => {
      disposed = true
      if (resizeFrame) cancelAnimationFrame(resizeFrame)
      resizeObserver?.disconnect()
      disposeResources()
      execWs?.dispose()
    }
  }, [containerId])

  return (
    <div className="workloads-terminal">
      <div className="workloads-terminal-header">
        <span>Terminal</span>
        <button
          type="button"
          onClick={onClose}
          className="icon-btn"
          aria-label="Close terminal"
        >
          ✕
        </button>
      </div>
      <div ref={containerRef} className="workloads-terminal-body" />
    </div>
  )
}
