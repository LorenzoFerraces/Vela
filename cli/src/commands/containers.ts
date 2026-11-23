import { parseArgs } from "node:util"

import { request, requireToken } from "../client"
import { resolveConfig } from "../config"
import { formatPorts, formatTable } from "../format"
import { emit } from "../output"
import { resolveContainerFromApi } from "../resolve"
import type { ContainerInfo, ContainerStats } from "../types"

export async function ps(argv: string[]): Promise<number> {
  parseArgs({ args: argv, options: {}, allowPositionals: false })
  const config = requireToken(resolveConfig({}))
  const containers = await request<ContainerInfo[]>(config, "GET", "/containers/")
  emit(containers, () => {
    const rows = containers.map((container) => [
      container.name,
      container.status,
      container.health,
      formatPorts(container.ports),
      container.access_url ?? "",
    ])
    return formatTable(["NAME", "STATUS", "HEALTH", "PORTS", "URL"], rows)
  })
  return 0
}

export async function describe(argv: string[]): Promise<number> {
  const { positionals } = parseArgs({
    args: argv,
    options: {},
    allowPositionals: true,
  })
  const query = positionals[0]
  if (!query) {
    console.error("Usage: vela describe <name|id>")
    return 2
  }
  const config = requireToken(resolveConfig({}))
  const container = await resolveContainerFromApi(config, query)

  let stats: ContainerStats | null = null
  try {
    stats = await request<ContainerStats>(
      config,
      "GET",
      `/containers/${container.id}/stats`,
    )
  } catch {
    stats = null
  }

  emit({ container, stats }, () => {
    const rows = [
      ["name", container.name],
      ["id", container.id],
      ["image", container.image],
      ["status", `${container.status} (${container.health})`],
      ["source", container.source_label ?? container.source_kind ?? ""],
      ["role", container.access_role ?? ""],
      ["ports", formatPorts(container.ports)],
      ["url", container.access_url ?? ""],
    ]
    if (stats) {
      rows.push(
        ["cpu", `${stats.cpu_percent.toFixed(1)}%`],
        ["memory", `${stats.memory_percent.toFixed(1)}%`],
      )
    }
    return formatTable(["FIELD", "VALUE"], rows)
  })
  return 0
}
