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
    <box style={{ flexDirection: "column", flexGrow: 1, padding: 1 }}>
      <text fg="#00FFFF">VELA // CONTAINERS</text>
      <box style={{ flexDirection: "row", flexGrow: 1, gap: 2 }}>
        <box style={{ flexDirection: "column", width: 42 }}>
          {containers.map((container, index) => (
            <text key={container.id} fg={index === selected ? "#00FF00" : "#FFFFFF"}>
              {index === selected ? ">" : " "} {container.name} [{container.status}]
            </text>
          ))}
        </box>
        <box style={{ flexDirection: "column", flexGrow: 1 }}>
          <text fg="#00FFFF">DETAIL</text>
          {current ? (
            <>
              <text>name   {current.name}</text>
              <text>id     {current.id}</text>
              <text>image  {current.image}</text>
              <text>status {current.status} ({current.health})</text>
              <text>ports  {formatPorts(current.ports)}</text>
              <text>url    {current.access_url ?? ""}</text>
            </>
          ) : (
            <text>no containers</text>
          )}
          <text fg="#FFFF00">LOGS</text>
          {logs.slice(-8).map((line, index) => (
            <text key={`${index}-${line}`}>{line}</text>
          ))}
        </box>
      </box>
      <text fg="#999999">
        up/down select  s start  x stop  l logs  e exec  q quit
      </text>
      {status ? <text fg="#FFFF00">{status}</text> : null}
    </box>
  )
}
