import { hostname } from "node:os"
import { parseArgs } from "node:util"

import { request, requireToken } from "../client"
import {
  DEFAULT_SERVER,
  clearStoredConfig,
  readStoredConfig,
  resolveConfig,
  writeStoredConfig,
} from "../config"
import { promptHidden, promptLine } from "../prompt"

interface LoginResponse {
  access_token: string
}

interface ApiTokenCreated {
  id: string
  name: string
  prefix: string
  created_at: string
  token: string
}

interface CurrentUser {
  email: string
  display_name?: string | null
}

export async function login(argv: string[]): Promise<number> {
  const { values } = parseArgs({
    args: argv,
    options: { server: { type: "string" } },
    allowPositionals: false,
  })
  const stored = readStoredConfig()
  const server = (values.server ?? process.env.VELA_API_URL ?? stored?.server ?? DEFAULT_SERVER)
    .replace(/\/+$/, "")

  const email = await promptLine("Email: ")
  const password = await promptHidden("Password: ")
  const auth = await request<LoginResponse>(
    { server },
    "POST",
    "/auth/login",
    { email, password },
  )
  const token = await request<ApiTokenCreated>(
    { server, token: auth.access_token },
    "POST",
    "/tokens/",
    { name: `cli:${hostname()}` },
  )

  writeStoredConfig({ server, token: token.token, tokenId: token.id })
  console.log(`Logged in to ${server} as ${email}.`)
  return 0
}

export async function logout(_argv: string[]): Promise<number> {
  const config = resolveConfig({})
  if (config.token && typeof config.tokenId === "string" && config.tokenId) {
    try {
      await request(config, "DELETE", `/tokens/${encodeURIComponent(config.tokenId)}`)
    } catch {
      // Already revoked or unreachable; clearing the local file is what matters.
    }
  }
  clearStoredConfig()
  console.log(
    config.tokenId
      ? "Logged out."
      : "Cleared local credentials. Revoke VELA_TOKEN where it was issued.",
  )
  return 0
}

export async function whoami(argv: string[]): Promise<number> {
  const { values } = parseArgs({
    args: argv,
    options: { json: { type: "boolean" } },
    allowPositionals: false,
  })
  const config = requireToken(resolveConfig({}))
  const me = await request<CurrentUser>(config, "GET", "/auth/me")
  if (values.json) {
    console.log(JSON.stringify(me, null, 2))
  } else {
    console.log(me.display_name ? `${me.display_name} <${me.email}>` : me.email)
  }
  return 0
}
