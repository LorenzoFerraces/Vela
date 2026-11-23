import { expect, test, beforeEach, afterEach } from "bun:test"
import { templatesCommand, scaleCommand, metricsCommand, auditCommand } from "./ops"

const originalFetch = globalThis.fetch
const originalConfig = process.env.VELA_CONFIG
const originalToken = process.env.VELA_TOKEN
const originalApiUrl = process.env.VELA_API_URL
const calls: { method: string; url: string; body?: string }[] = []
beforeEach(() => {
  calls.length = 0
  process.env.VELA_CONFIG = ""
  process.env.VELA_TOKEN = "pat_test"
  process.env.VELA_API_URL = "http://127.0.0.1:8000"
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const entry: { method: string; url: string; body?: string } = { method: init?.method ?? "GET", url }
    if (typeof init?.body === "string") entry.body = init.body
    calls.push(entry)
    const body = url.includes("audit") ? JSON.stringify({ entries: [], total: 0 }) : JSON.stringify([])
    return new Response(body, { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalConfig === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = originalConfig
  if (originalToken === undefined) delete process.env.VELA_TOKEN; else process.env.VELA_TOKEN = originalToken
  if (originalApiUrl === undefined) delete process.env.VELA_API_URL; else process.env.VELA_API_URL = originalApiUrl
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
test("scale set merges metric and thresholds into the existing policy", async () => {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const entry: { method: string; url: string; body?: string } = { method: init?.method ?? "GET", url }
    if (typeof init?.body === "string") entry.body = init.body
    calls.push(entry)
    if (init?.method === "GET") {
      return new Response(JSON.stringify({
        id: "p1", container_name: "web", enabled: false, min_replicas: 2, max_replicas: 9,
        metric: "memory_percent", scale_up_threshold: 70, scale_down_threshold: 30,
        cooldown_seconds: 120, scale_up_stabilization_seconds: 300, scale_down_stabilization_seconds: 240,
        last_scaled_at: null, created_at: "now", updated_at: "now",
      }), { status: 200, headers: { "content-type": "application/json" } })
    }
    return new Response(JSON.stringify({ container_name: "web" }), {
      status: 200, headers: { "content-type": "application/json" },
    })
  }) as typeof fetch
  expect(await scaleCommand(["set", "web", "cpu_percent", "80"])).toBe(0)
  const put = calls.find((call) => call.method === "PUT")!
  expect(JSON.parse(put.body!)).toEqual({
    enabled: false, min_replicas: 2, max_replicas: 9, metric: "cpu_percent",
    scale_up_threshold: 80, scale_down_threshold: 40, cooldown_seconds: 120,
    scale_up_stabilization_seconds: 300, scale_down_stabilization_seconds: 240,
  })
})

test("scale set creates a fresh policy when none exists", async () => {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const entry: { method: string; url: string; body?: string } = { method: init?.method ?? "GET", url }
    if (typeof init?.body === "string") entry.body = init.body
    calls.push(entry)
    if (init?.method === "GET") {
      return new Response(JSON.stringify({ detail: "No scaling policy found" }), {
        status: 404, headers: { "content-type": "application/json" },
      })
    }
    return new Response(JSON.stringify({ container_name: "web" }), {
      status: 200, headers: { "content-type": "application/json" },
    })
  }) as typeof fetch
  expect(await scaleCommand(["set", "web", "cpu_percent", "80"])).toBe(0)
  const put = calls.find((call) => call.method === "PUT")!
  expect(JSON.parse(put.body!)).toEqual({ metric: "cpu_percent", scale_up_threshold: 80, scale_down_threshold: 40 })
})

test("metrics summary resolves a container name to its id", async () => {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    const entry: { method: string; url: string } = { method: "GET", url }
    calls.push(entry)
    return new Response(JSON.stringify({ id: "ctr_1", name: "web", status: "running" }), {
      status: 200, headers: { "content-type": "application/json" },
    })
  }) as typeof fetch
  expect(await metricsCommand(["summary", "--container", "web", "--hours", "12"])).toBe(0)
  expect(calls.some((call) => call.url.includes("/metrics/summary?container_id=ctr_1&hours=12"))).toBe(true)
})

test("audit defaults to the user-scoped log", async () => {
  expect(await auditCommand(["list"])).toBe(0)
  expect(calls[0].url).toContain("/api/audit/log")
})
test("audit --global uses the admin endpoint", async () => {
  expect(await auditCommand(["list", "--global"])).toBe(0)
  expect(calls[0].url).toContain("/api/admin/audit")
})
