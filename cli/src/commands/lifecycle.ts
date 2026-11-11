import { parseArgs } from "node:util"

import { request, requireToken, VelaError } from "../client"
import { resolveConfig } from "../config"
import { promptLine } from "../prompt"
import { resolveContainerFromApi } from "../resolve"
import type { ContainerInfo } from "../types"

function parseTarget(argv: string[]) {
  const { values, positionals } = parseArgs({
    args: argv,
    options: { yes: { type: "boolean", short: "y" } },
    allowPositionals: true,
  })
  const query = positionals[0]
  if (!query) throw new VelaError(2, "Missing container name.")
  return { query, yes: values.yes ?? false }
}

async function act(action: string, argv: string[]): Promise<number> {
  const { query } = parseTarget(argv)
  const config = requireToken(resolveConfig({}))
  const container = await resolveContainerFromApi(config, query)
  const updated = await request<ContainerInfo>(
    config,
    "POST",
    `/containers/${container.id}/${action}`,
  )
  console.log(`${updated.name}: ${updated.status}`)
  return 0
}

export async function start(argv: string[]): Promise<number> {
  return await act("start", argv)
}

export async function stop(argv: string[]): Promise<number> {
  return await act("stop", argv)
}

export async function restart(argv: string[]): Promise<number> {
  return await act("restart", argv)
}

export async function remove(argv: string[]): Promise<number> {
  const { query, yes } = parseTarget(argv)
  const config = requireToken(resolveConfig({}))
  const container = await resolveContainerFromApi(config, query)
  if (!yes) {
    const answer = await promptLine(`Remove container "${container.name}"? [y/N] `)
    if (answer.toLowerCase() !== "y") {
      console.log("Cancelled.")
      return 0
    }
  }
  await request(config, "DELETE", `/containers/${container.id}`)
  console.log(`Removed ${container.name}.`)
  return 0
}
