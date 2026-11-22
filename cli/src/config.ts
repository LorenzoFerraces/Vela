import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync, chmodSync } from "node:fs"
import { dirname, join } from "node:path"
import { homedir } from "node:os"

export const DEFAULT_SERVER = "http://127.0.0.1:8000"
const DEFAULT_PROFILE = "default"

interface LegacyConfig { server?: unknown; token?: unknown; tokenId?: unknown }
export interface ConfigProfile { server: string; token: string; tokenId?: string }
export interface StoredConfig { profiles: Record<string, ConfigProfile>; active: string }
export interface ResolvedConfig { server: string; token?: string; tokenId?: string; profile: string }

export function configPath(env: NodeJS.ProcessEnv = process.env): string {
  return env.VELA_CONFIG ?? join(homedir(), ".vela", "config.json")
}

function readProfile(value: unknown): ConfigProfile | null {
  if (!value || typeof value !== "object") return null
  const candidate = value as Record<string, unknown>
  if (typeof candidate.server !== "string" || typeof candidate.token !== "string") return null
  return {
    server: candidate.server,
    token: candidate.token,
    ...(typeof candidate.tokenId === "string" ? { tokenId: candidate.tokenId } : {}),
  }
}

export function readStoredConfig(path: string = configPath()): StoredConfig | null {
  try {
    if (!existsSync(path)) return null
    const parsed = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>
    if (parsed.profiles && typeof parsed.profiles === "object") {
      const profiles: Record<string, ConfigProfile> = {}
      for (const [name, value] of Object.entries(parsed.profiles as Record<string, unknown>)) {
        const profile = readProfile(value)
        if (profile) profiles[name] = profile
      }
      if (!Object.keys(profiles).length) return null
      const active = typeof parsed.active === "string" && profiles[parsed.active]
        ? parsed.active
        : Object.keys(profiles)[0]
      return { profiles, active }
    }
    const legacy = parsed as LegacyConfig
    if (typeof legacy.server === "string" && typeof legacy.token === "string") {
      const migrated: StoredConfig = {
        profiles: { [DEFAULT_PROFILE]: {
          server: legacy.server, token: legacy.token,
          ...(typeof legacy.tokenId === "string" ? { tokenId: legacy.tokenId } : {}),
        } },
        active: DEFAULT_PROFILE,
      }
      writeStoredConfig(migrated, path)
      return migrated
    }
    return null
  } catch { return null }
}

export function writeStoredConfig(config: StoredConfig, path: string = configPath()): void {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, JSON.stringify(config, null, 2) + "\n", { mode: 0o600 })
  try { chmodSync(path, 0o600) } catch { /* Windows: mode is advisory, ACLs govern access. */ }
}

export function clearStoredConfig(path: string = configPath()): void {
  rmSync(path, { force: true })
}

export function resolveConfig(
  flags: { server?: string; token?: string; profile?: string },
  env: NodeJS.ProcessEnv = process.env,
  stored: StoredConfig | null = readStoredConfig(),
): ResolvedConfig {
  const profileName = flags.profile ?? env.VELA_PROFILE ?? stored?.active ?? DEFAULT_PROFILE
  const profile = stored?.profiles[profileName] ?? stored?.profiles[stored.active] ?? null
  const server = (flags.server ?? env.VELA_API_URL ?? profile?.server ?? DEFAULT_SERVER).replace(/\/+$/, "")
  const fromOverride = flags.token !== undefined || env.VELA_TOKEN !== undefined
  return {
    server,
    token: flags.token ?? env.VELA_TOKEN ?? profile?.token,
    tokenId: fromOverride ? undefined : profile?.tokenId,
    profile: stored?.profiles[profileName] ? profileName : (stored?.active ?? DEFAULT_PROFILE),
  }
}
