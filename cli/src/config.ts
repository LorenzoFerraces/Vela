import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, join } from "node:path"

export const DEFAULT_SERVER = "http://127.0.0.1:8000"

export interface StoredConfig {
  server: string
  token: string
  tokenId?: string
}

export interface ResolvedConfig {
  server: string
  token?: string
  tokenId?: string
}

export function configPath(env: NodeJS.ProcessEnv = process.env): string {
  return env.VELA_CONFIG ?? join(homedir(), ".vela", "config.json")
}

export function readStoredConfig(path: string = configPath()): StoredConfig | null {
  if (!existsSync(path)) return null
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as Partial<StoredConfig>
    if (typeof parsed.server !== "string" || typeof parsed.token !== "string") return null
    return { server: parsed.server, token: parsed.token, tokenId: parsed.tokenId }
  } catch {
    return null
  }
}

export function writeStoredConfig(
  config: StoredConfig,
  path: string = configPath(),
): void {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 })
  try {
    chmodSync(path, 0o600)
  } catch {
    // Windows: mode is advisory, ACLs govern access.
  }
}

export function clearStoredConfig(path: string = configPath()): void {
  rmSync(path, { force: true })
}

export function resolveConfig(
  flags: { server?: string; token?: string },
  env: NodeJS.ProcessEnv = process.env,
  stored: StoredConfig | null = readStoredConfig(),
): ResolvedConfig {
  const server = (flags.server ?? env.VELA_API_URL ?? stored?.server ?? DEFAULT_SERVER)
    .replace(/\/+$/, "")
  const fromOverride = flags.token ?? env.VELA_TOKEN
  return {
    server,
    token: fromOverride ?? stored?.token,
    tokenId: fromOverride ? undefined : stored?.tokenId,
  }
}
