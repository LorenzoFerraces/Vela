import { useEffect, useRef } from 'react'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import 'xterm/css/xterm.css'
import { openContainerExecWebSocket } from '../../api/client'
import type { ExecWebSocketHandle } from '../../api/client'

interface ContainerTerminalProps {
  containerId: string
  onClose: () => void
}

export function ContainerTerminal({ containerId, onClose }: ContainerTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<ExecWebSocketHandle | null>(null)

  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", Menlo, monospace',
      theme: { background: '#1e1e2e', foreground: '#cdd6f4' },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)

    termRef.current = term
    fitRef.current = fit

    if (!containerRef.current) return
    term.open(containerRef.current)
    fit.fit()

    const execWs = openContainerExecWebSocket(
      containerId,
      () => {
        execWs.send(JSON.stringify({ cols: term.cols, rows: term.rows }))
      },
      (data) => term.write(data),
      () => term.write('\r\n\x1b[31m[connection closed]\x1b[0m\r\n'),
      () => term.write('\r\n\x1b[31m[connection error]\x1b[0m\r\n'),
    )
    wsRef.current = execWs

    term.onData((chr) => execWs.send(chr))

    const resizeObserver = new ResizeObserver(() => {
      fit.fit()
      execWs.send(JSON.stringify({ resize: { cols: term.cols, rows: term.rows } }))
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      execWs.dispose()
      resizeObserver.disconnect()
      term.dispose()
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
