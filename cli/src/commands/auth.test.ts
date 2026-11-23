import { afterEach, beforeEach, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { login } from "./auth"
import { readStoredConfig, writeStoredConfig } from "../config"

const savedEnv = { ...process.env }
const originalFetch = globalThis.fetch
let directory = ""
const calls: string[] = []

beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), "vela-auth-"))
  process.env.VELA_CONFIG = join(directory, "config.json")
  process.env.VELA_LOGIN_EMAIL = "me@example.com"
  process.env.VELA_LOGIN_PASSWORD = "pw"
  calls.length = 0
})

afterEach(() => {
  globalThis.fetch = originalFetch
  process.env = { ...savedEnv }
  rmSync(directory, { recursive: true, force: true })
})

function mockFetch(): void {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    if (url.includes("/auth/login")) {
      return new Response(JSON.stringify({ access_token: "auth-token" }), {
        status: 200, headers: { "content-type": "application/json" },
      })
    }
    return new Response(JSON.stringify({ id: "tid_new", name: "cli", prefix: "pat_", created_at: "now", token: "pat_new" }), {
      status: 200, headers: { "content-type": "application/json" },
    })
  }) as typeof fetch
}

test("VELA_PROFILE chooses the login server and write target without changing active", async () => {
  writeStoredConfig({ profiles: {
    default: { server: "http://default:8000", token: "t_default" },
    staging: { server: "http://staging:8000", token: "t_staging" },
  }, active: "default" })
  process.env.VELA_PROFILE = "staging"
  mockFetch()
  expect(await login([])).toBe(0)
  expect(calls[0]).toContain("http://staging:8000/api/auth/login")
  const stored = readStoredConfig()!
  expect(stored.profiles.staging).toEqual({ server: "http://staging:8000", token: "pat_new", tokenId: "tid_new" })
  expect(stored.profiles.default.token).toBe("t_default")
  expect(stored.active).toBe("default")
})

test("login merges into the freshest profile map before writing", async () => {
  writeStoredConfig({ profiles: { default: { server: "http://default:8000", token: "t_default" } }, active: "default" })
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    if (url.includes("/auth/login")) {
      return new Response(JSON.stringify({ access_token: "auth-token" }), {
        status: 200, headers: { "content-type": "application/json" },
      })
    }
    const current = readStoredConfig()!
    writeStoredConfig({
      ...current,
      profiles: { ...current.profiles, other: { server: "http://other:8000", token: "t_other" } },
    })
    return new Response(JSON.stringify({ id: "tid_new", name: "cli", prefix: "pat_", created_at: "now", token: "pat_new" }), {
      status: 200, headers: { "content-type": "application/json" },
    })
  }) as typeof fetch
  expect(await login([])).toBe(0)
  const stored = readStoredConfig()!
  expect(stored.profiles.other).toEqual({ server: "http://other:8000", token: "t_other" })
  expect(stored.profiles.default.token).toBe("pat_new")
})
