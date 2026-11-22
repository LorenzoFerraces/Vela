import { parseArgs } from "node:util"
import { readStoredConfig, writeStoredConfig, clearStoredConfig, configPath } from "../config"
import { VelaError } from "../client"

export async function configCommand(argv: string[]): Promise<number> {
  const action = argv[0] ?? "list"
  const { values, positionals } = parseArgs({
    args: argv.slice(1),
    options: { profile: { type: "string" } },
    allowPositionals: true,
  })
  const path = configPath()
  const stored = readStoredConfig(path) ?? { profiles: {}, active: "default" }
  const profileName = values.profile ?? process.env.VELA_PROFILE ?? stored.active

  if (action === "list") {
    for (const [name, profile] of Object.entries(stored.profiles)) {
      console.log(`${name === stored.active ? "*" : " "} ${name}  ${profile.server}`)
    }
    return 0
  }
  if (action === "use") {
    const name = positionals[0]
    if (!name || !Object.hasOwn(stored.profiles, name)) throw new VelaError(2, `Unknown profile: ${name ?? "(none)"}`)
    writeStoredConfig({ ...stored, active: name }, path)
    console.log(`Active profile: ${name}`)
    return 0
  }
  if (action === "get") {
    const key = positionals[0]
    const profile = Object.hasOwn(stored.profiles, profileName) ? stored.profiles[profileName] : null
    if (!profile) throw new VelaError(2, `Unknown profile: ${profileName}`)
    if (!key || key === "server") { console.log(profile.server); return 0 }
    if (key === "token") { console.log(profile.token ? "<set>" : "<unset>"); return 0 }
    if (key === "tokenId") { console.log(profile.tokenId ?? "<unset>"); return 0 }
    if (key === "active") { console.log(stored.active); return 0 }
    throw new VelaError(2, `Unknown key: ${key}`)
  }
  if (action === "set") {
    const key = positionals[0]
    const value = positionals[1]
    if (!key || value === undefined) throw new VelaError(2, "Usage: vela config set <server|token> <value> [--profile <name>]")
    if (key !== "server" && key !== "token") throw new VelaError(2, `Unknown key: ${key}`)
    const current = Object.hasOwn(stored.profiles, profileName) ? stored.profiles[profileName] : { server: "", token: "" }
    const next = { ...current, [key]: value }
    if (key === "token") delete next.tokenId
    writeStoredConfig({ profiles: { ...stored.profiles, [profileName]: next }, active: stored.active }, path)
    console.log(`Updated ${key} in profile ${profileName}`)
    return 0
  }
  if (action === "clear") {
    clearStoredConfig(path)
    console.log("Config removed")
    return 0
  }
  throw new VelaError(2, `Unknown config action: ${action}`)
}
