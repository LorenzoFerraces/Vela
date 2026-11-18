import { createCliRenderer } from "@opentui/core"
import { createRoot } from "@opentui/react"

import { request, requireToken, VelaError } from "../client"
import { resolveConfig } from "../config"
import { App } from "./app"
import type { ContainerInfo } from "../types"

export async function runTui(): Promise<number> {
  if (!process.stdout.isTTY) {
    throw new VelaError(2, "TUI requires a terminal.")
  }
  const config = requireToken(resolveConfig({}))

  const renderer = await createCliRenderer({
    exitOnCtrlC: true,
    backgroundColor: "#0c0d12",
  })
  const root = createRoot(renderer)

  const load = async () =>
    await request<ContainerInfo[]>(config, "GET", "/containers/")
  const act = (action: "start" | "stop") => async (container: ContainerInfo) => {
    await request(config, "POST", `/containers/${container.id}/${action}`)
  }
  const run = async (source: string) => {
    const isGit =
      source.startsWith("git@") ||
      source.startsWith("http://") ||
      source.startsWith("https://") ||
      source.startsWith("ssh://")
    const body = isGit
      ? { source_kind: "git", git_url: source, git_branch: "main" }
      : { source_kind: "image", image_ref: source }
    await request(config, "POST", "/containers/run", body)
  }

  let finish: () => void = () => {}
  const done = new Promise<void>((resolve) => {
    finish = resolve
  })
  const quit = () => {
    renderer.destroy()
    finish()
  }

  let initialContainers: ContainerInfo[]
  try {
    initialContainers = await load()
  } catch (error) {
    renderer.destroy()
    throw error
  }

  root.render(
    <App
      load={load}
      initialContainers={initialContainers}
      onStart={act("start")}
      onStop={act("stop")}
      onRun={run}
      onExec={(container) => {
        renderer.destroy()
        console.log(`Run: vela exec ${container.name}`)
        finish()
      }}
      onQuit={quit}
    />,
  )

  await done
  return 0
}
