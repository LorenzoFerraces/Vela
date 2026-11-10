import { useEffect, useState } from "react"
import { useKeyboard } from "@opentui/react"

import { formatPorts } from "../format"
import type { ContainerInfo } from "../types"

export interface AppProps {
  initialContainers?: ContainerInfo[]
  load?: () => Promise<ContainerInfo[]>
  onStart?: (container: ContainerInfo) => Promise<void>
  onStop?: (container: ContainerInfo) => Promise<void>
  onExec?: (container: ContainerInfo) => void
  onQuit?: () => void
}

const colors = {
  background: "#0c0d12",
  panel: "#111218",
  border: "#2a2c3a",
  borderActive: "#7c5cff",
  text: "#e6e6f0",
  dim: "#6f7186",
  accent: "#7c5cff",
  running: "#3ddc84",
  stopped: "#ff6b6b",
  pending: "#f5c451",
}

function statusColor(status: string): string {
  if (status === "running") return colors.running
  if (status === "starting" || status === "restarting") return colors.pending
  if (status === "stopped" || status === "exited") return colors.stopped
  return colors.dim
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <text>
      <span fg={colors.dim}>{label.padEnd(8)}</span>
      <span fg={colors.text}>{value}</span>
    </text>
  )
}

function Key({ name, label }: { name: string; label: string }) {
  return (
    <text>
      <span fg={colors.accent}>{name}</span>
      <span fg={colors.dim}> {label}</span>
    </text>
  )
}

export function App({
  initialContainers = [],
  load,
  onStart,
  onStop,
  onExec,
  onQuit,
}: AppProps) {
  const [containers, setContainers] = useState<ContainerInfo[]>(initialContainers)
  const [selected, setSelected] = useState(0)
  const [logs, setLogs] = useState<string[]>([])
  const [status, setStatus] = useState("")

  useEffect(() => {
    if (!load) return
    let cancelled = false
    const refresh = async () => {
      try {
        const next = await load()
        if (!cancelled) setContainers(next)
      } catch (error) {
        if (!cancelled) setStatus(error instanceof Error ? error.message : String(error))
      }
    }
    void refresh()
    const timer = setInterval(() => void refresh(), 5000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [load])

  const current = containers[selected]

  useKeyboard((key) => {
    if (key.name === "q") {
      onQuit?.()
      return
    }
    if (key.name === "down") {
      setSelected((index) => Math.min(index + 1, Math.max(containers.length - 1, 0)))
      return
    }
    if (key.name === "up") {
      setSelected((index) => Math.max(index - 1, 0))
      return
    }
    if (key.name === "s" && current && onStart) {
      void onStart(current)
        .then(() => setStatus(`started ${current.name}`))
        .catch((error: unknown) =>
          setStatus(error instanceof Error ? error.message : String(error)),
        )
      return
    }
    if (key.name === "x" && current && onStop) {
      void onStop(current)
        .then(() => setStatus(`stopped ${current.name}`))
        .catch((error: unknown) =>
          setStatus(error instanceof Error ? error.message : String(error)),
        )
      return
    }
    if (key.name === "l" && current) {
      setLogs((lines) => [...lines, `-- following ${current.name} is handled by: vela logs ${current.name} -f`])
      return
    }
    if (key.name === "e" && current && onExec) {
      onExec(current)
    }
  })

  return (
    <box style={{ flexDirection: "column", flexGrow: 1, backgroundColor: colors.background, padding: 0 }}>
      <box
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          paddingLeft: 1,
          paddingRight: 1,
          paddingTop: 1,
        }}
      >
        <text>
          <strong fg={colors.accent}>VELA</strong>
          <span fg={colors.dim}> // containers</span>
        </text>
        <text fg={colors.dim}>
          {containers.length} {containers.length === 1 ? "workload" : "workloads"}
        </text>
      </box>

      <box style={{ flexDirection: "row", flexGrow: 1, gap: 1, padding: 1, paddingTop: 1 }}>
        <box
          title={` CONTAINERS `}
          titleColor={colors.accent}
          border
          borderStyle="rounded"
          borderColor={colors.border}
          style={{ flexDirection: "column", width: 36, padding: 0, paddingLeft: 1 }}
        >
          {containers.length === 0 ? (
            <text fg={colors.dim}>no containers · vela run &lt;image&gt;</text>
          ) : (
            containers.map((container, index) => (
              <text key={container.id} bg={index === selected ? "#1a1730" : undefined}>
                <span fg={index === selected ? colors.accent : colors.dim}>
                  {index === selected ? "▸ " : "  "}
                </span>
                <span fg={statusColor(container.status)}>● </span>
                <span fg={index === selected ? colors.text : colors.dim}>{container.name}</span>
                <span fg={colors.border}> {container.status}</span>
              </text>
            ))
          )}
        </box>

        <box
          title={` DETAIL `}
          titleColor={colors.accent}
          border
          borderStyle="rounded"
          borderColor={colors.border}
          style={{ flexDirection: "column", flexGrow: 1, padding: 1 }}
        >
          {current ? (
            <>
              <text>
                <strong fg={colors.text}>{current.name}</strong>
              </text>
              <text fg={colors.dim}>{current.id}</text>
              <text> </text>
              <Field label="image" value={current.image} />
              <Field label="status" value={`${current.status} (${current.health})`} />
              <Field label="ports" value={formatPorts(current.ports) || "-"} />
              <Field label="url" value={current.access_url ?? "-"} />
            </>
          ) : (
            <text fg={colors.dim}>no container selected</text>
          )}
          {logs.length > 0 ? (
            <>
              <text> </text>
              <text fg={colors.accent}>LOGS</text>
              {logs.slice(-8).map((line, index) => (
                <text key={`${index}-${line}`} fg={colors.dim}>
                  {line}
                </text>
              ))}
            </>
          ) : null}
        </box>
      </box>

      <box
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          paddingLeft: 1,
          paddingRight: 1,
        }}
      >
        <text>
          {status ? (
            <span fg={colors.pending}>{status}</span>
          ) : (
            <span fg={colors.dim}>ready</span>
          )}
        </text>
      </box>

      <box
        style={{
          flexDirection: "row",
          gap: 2,
          paddingLeft: 1,
          paddingRight: 1,
          paddingBottom: 1,
        }}
      >
        <Key name="↑↓" label="select" />
        <Key name="s" label="start" />
        <Key name="x" label="stop" />
        <Key name="l" label="logs" />
        <Key name="e" label="exec" />
        <Key name="q" label="quit" />
      </box>
    </box>
  )
}
