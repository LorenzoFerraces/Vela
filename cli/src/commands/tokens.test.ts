import { afterEach, beforeEach, expect, test } from "bun:test"

import { tokens } from "./tokens"

const savedEnv = { ...process.env }
const originalFetch = globalThis.fetch

beforeEach(() => {
  process.env.VELA_CONFIG = ""
  process.env.VELA_TOKEN = "pat_test"
  delete process.env.VELA_OUTPUT_QUIET
  delete process.env.VELA_OUTPUT_JSON
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "DELETE") return new Response(null, { status: 200 })
    return new Response(JSON.stringify([
      { id: "tok_1", name: "old", prefix: "pat_old", created_at: "now" },
    ]), { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
})

afterEach(() => {
  globalThis.fetch = originalFetch
  process.env = { ...savedEnv }
})

function capture(): { lines: string[]; restore: () => void } {
  const lines: string[] = []
  const log = console.log
  console.log = (value: string) => lines.push(value)
  return { lines, restore: () => { console.log = log } }
}

test("revoke confirmation is byte-identical in ordinary mode", async () => {
  const { lines, restore } = capture()
  try { expect(await tokens(["revoke", "old"])).toBe(0) } finally { restore() }
  expect(lines).toEqual(["Revoked old."])
})

test("revoke confirmation is suppressed by --quiet", async () => {
  process.env.VELA_OUTPUT_QUIET = "1"
  const { lines, restore } = capture()
  try { expect(await tokens(["revoke", "old"])).toBe(0) } finally { restore() }
  expect(lines).toEqual([])
})

test("revoke confirmation emits an object under --json", async () => {
  process.env.VELA_OUTPUT_JSON = "1"
  const { lines, restore } = capture()
  try { expect(await tokens(["revoke", "old"])).toBe(0) } finally { restore() }
  expect(JSON.parse(lines.join("\n"))).toEqual({ revoked: "old", id: "tok_1" })
})
