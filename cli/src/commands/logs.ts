import { parseArgs } from "node:util"

import { requireToken } from "../client"
import { resolveConfig } from "../config"
import { resolveContainerFromApi } from "../resolve"
import { streamLogs } from "../ws"

export async function logs(argv: string[]): Promise<number> {
  const { values, positionals } = parseArgs({
    args: argv,
    options: {
      follow: { type: "boolean", short: "f" },
      tail: { type: "string", short: "n" },
    },
    allowPositionals: true,
  })
  const query = positionals[0]
  if (!query) {
    console.error("Usage: vela logs <name> [-f] [-n 200]")
    return 2
  }
  const tail = values.tail ? Number(values.tail) : 200
  if (!Number.isInteger(tail) || tail < 1) {
    console.error(`Invalid --tail "${values.tail}".`)
    return 2
  }

  const config = requireToken(resolveConfig({}))
  const container = await resolveContainerFromApi(config, query)
  await streamLogs(config, container.id, { tail, follow: values.follow ?? false })
  return 0
}
