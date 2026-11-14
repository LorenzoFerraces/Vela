import { parseArgs } from "node:util"

import { request, requireToken, VelaError } from "../client"
import { resolveConfig } from "../config"
import { formatTable } from "../format"

interface ApiTokenPublic {
  id: string
  name: string
  prefix: string
  created_at: string
}

interface ApiTokenCreated extends ApiTokenPublic {
  token: string
}

export async function tokens(argv: string[]): Promise<number> {
  const { values, positionals } = parseArgs({
    args: argv,
    options: {
      json: { type: "boolean" },
      name: { type: "string" },
    },
    allowPositionals: true,
  })
  const action = positionals[0] ?? "list"
  const config = requireToken(resolveConfig({}))

  if (action === "list") {
    const items = await request<ApiTokenPublic[]>(config, "GET", "/tokens/")
    if (values.json) {
      console.log(JSON.stringify(items, null, 2))
      return 0
    }
    const rows = items.map((item) => [item.name, item.prefix, item.created_at])
    console.log(formatTable(["NAME", "PREFIX", "CREATED"], rows))
    return 0
  }

  if (action === "create") {
    const name = values.name ?? positionals[1]
    if (!name) throw new VelaError(2, "Usage: vela tokens create --name <label>")
    const created = await request<ApiTokenCreated>(config, "POST", "/tokens/", { name })
    console.log(created.token)
    console.log("Store this token now; it is shown only once.")
    return 0
  }

  if (action === "revoke") {
    const target = positionals[1]
    if (!target) throw new VelaError(2, "Usage: vela tokens revoke <prefix|name>")
    const items = await request<ApiTokenPublic[]>(config, "GET", "/tokens/")
    const match = items.find(
      (item) => item.prefix === target || item.name === target,
    )
    if (!match) throw new VelaError(4, `No token matching "${target}".`)
    await request(config, "DELETE", `/tokens/${match.id}`)
    console.log(`Revoked ${match.name}.`)
    return 0
  }

  throw new VelaError(2, `Unknown tokens action "${action}". Use list, create, or revoke.`)
}
