import { expect, test, beforeEach, afterEach } from "bun:test"
import { stackCommand, projectsCommand, inviteCommand } from "./organisation"

const originalFetch = globalThis.fetch
const originalConfig = process.env.VELA_CONFIG
const originalToken = process.env.VELA_TOKEN
const originalApiUrl = process.env.VELA_API_URL
const calls: { method: string; url: string }[] = []
beforeEach(() => {
  calls.length = 0
  process.env.VELA_CONFIG = ""
  process.env.VELA_TOKEN = "pat_test"
  process.env.VELA_API_URL = "http://127.0.0.1:8000"
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ method: init?.method ?? "GET", url: String(input) })
    return new Response(JSON.stringify([]), { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalConfig === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = originalConfig
  if (originalToken === undefined) delete process.env.VELA_TOKEN; else process.env.VELA_TOKEN = originalToken
  if (originalApiUrl === undefined) delete process.env.VELA_API_URL; else process.env.VELA_API_URL = originalApiUrl
})

test("stack list hits GET /api/stacks/", async () => {
  expect(await stackCommand(["list"])).toBe(0)
  expect(calls[0]).toEqual({ method: "GET", url: "http://127.0.0.1:8000/api/stacks/" })
})

test("projects create posts the name", async () => {
  expect(await projectsCommand(["create", "class-a"])).toBe(0)
  expect(calls[0].method).toBe("POST")
  expect(calls[0].url).toContain("/api/projects/")
})

test("invite list hits the project-scoped invitations endpoint", async () => {
  expect(await inviteCommand(["list", "--project", "prj_1"])).toBe(0)
  expect(calls[0].url).toContain("/api/projects/prj_1/invitations")
})
