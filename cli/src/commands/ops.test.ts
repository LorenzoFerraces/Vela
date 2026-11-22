import { expect, test, beforeEach, afterEach } from "bun:test"
import { templatesCommand, scaleCommand, metricsCommand, auditCommand } from "./ops"

const originalFetch = globalThis.fetch
const originalConfig = process.env.VELA_CONFIG
const originalToken = process.env.VELA_TOKEN
const calls: { method: string; url: string }[] = []
beforeEach(() => {
  calls.length = 0
  process.env.VELA_CONFIG = ""
  process.env.VELA_TOKEN = "pat_test"
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ method: init?.method ?? "GET", url })
    const body = url.includes("audit") ? JSON.stringify({ entries: [], total: 0 }) : JSON.stringify([])
    return new Response(body, { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalConfig === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = originalConfig
  if (originalToken === undefined) delete process.env.VELA_TOKEN; else process.env.VELA_TOKEN = originalToken
})

test("templates list hits GET /api/dockerfiles/", async () => {
  expect(await templatesCommand(["list"])).toBe(0)
  expect(calls[0]).toEqual({ method: "GET", url: "http://127.0.0.1:8000/api/dockerfiles/" })
})
test("scale read uses GET /api/scaling/policies", async () => {
  expect(await scaleCommand(["list"])).toBe(0)
  expect(calls[0].url).toContain("/api/scaling/policies")
})
test("metrics usage hits GET /api/metrics/usage", async () => {
  expect(await metricsCommand(["usage"])).toBe(0)
  expect(calls[0].url).toContain("/api/metrics/usage")
})
test("audit defaults to the user-scoped log", async () => {
  expect(await auditCommand(["list"])).toBe(0)
  expect(calls[0].url).toContain("/api/audit/log")
})
test("audit --global uses the admin endpoint", async () => {
  expect(await auditCommand(["list", "--global"])).toBe(0)
  expect(calls[0].url).toContain("/api/admin/audit")
})
