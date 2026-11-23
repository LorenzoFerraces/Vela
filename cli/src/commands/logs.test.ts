import { expect, test, beforeEach, afterEach } from "bun:test"
import { logs } from "./logs"

const originalFetch = globalThis.fetch
const originalConfig = process.env.VELA_CONFIG
const originalToken = process.env.VELA_TOKEN
const calls: string[] = []
beforeEach(() => {
  calls.length = 0
  process.env.VELA_CONFIG = ""
  process.env.VELA_TOKEN = "pat_test"
})
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalConfig === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = originalConfig
  if (originalToken === undefined) delete process.env.VELA_TOKEN; else process.env.VELA_TOKEN = originalToken
})

test("a failed stream falls back to the HTTP log snapshot", async () => {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    if (url.includes("/by-name/")) {
      return new Response(JSON.stringify({ id: "c1", name: "web", status: "exited" }), { status: 200, headers: { "content-type": "application/json" } })
    }
    if (url.includes("/logs")) {
      return new Response(JSON.stringify({ logs: "line one\nline two" }), { status: 200, headers: { "content-type": "application/json" } })
    }
    return new Response("[]", { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
  const lines: string[] = []
  const log = console.log; console.log = (value: string) => lines.push(value)
  try { expect(await logs(["web"])).toBe(0) } finally { console.log = log }
  expect(calls.some((url) => url.includes("/api/containers/c1/logs"))).toBe(true)
  expect(lines.join("\n")).toContain("line one")
})
