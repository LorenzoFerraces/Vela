import { expect, test, beforeEach, afterEach } from "bun:test"
import { imagesCommand, sourcesCommand, settingsCommand, githubCommand } from "./platform"

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
    const body = url.includes("deploy-sources") ? JSON.stringify({ suggestions: [] })
      : url.includes("/api/images/") && !url.includes("/pull") ? JSON.stringify({ images: [] })
      : JSON.stringify([])
    return new Response(body, { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalConfig === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = originalConfig
  if (originalToken === undefined) delete process.env.VELA_TOKEN; else process.env.VELA_TOKEN = originalToken
})

test("images list hits GET /api/images/", async () => {
  expect(await imagesCommand(["list"])).toBe(0)
  expect(calls[0]).toEqual({ method: "GET", url: "http://127.0.0.1:8000/api/images/" })
})
test("images pull posts to the admin endpoint", async () => {
  expect(await imagesCommand(["pull", "nginx", "--tag", "1.27"])).toBe(0)
  expect(calls[0].method).toBe("POST")
  expect(calls[0].url).toContain("/api/images/pull?image=nginx&tag=1.27")
})
test("sources list hits /api/containers/deploy-sources", async () => {
  expect(await sourcesCommand(["list"])).toBe(0)
  expect(calls[0].url).toContain("/api/containers/deploy-sources")
})
test("sources list renders image suggestions by ref/label and others by name", async () => {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push({ method: "GET", url: String(input) })
    return new Response(JSON.stringify({ suggestions: [
      { kind: "image", ref: "nginx:alpine", label: "nginx:alpine" },
      { kind: "git", url: "https://github.com/o/r.git", name: "r", default_branch: "main" },
      { kind: "dockerfile_template", id: "tpl_1", name: "tpl" },
    ] }), { status: 200, headers: { "content-type": "application/json" } })
  }) as typeof fetch
  const lines: string[] = []
  const log = console.log; console.log = (value: string) => lines.push(value)
  try { expect(await sourcesCommand(["list"])).toBe(0) } finally { console.log = log }
  const output = lines.join("\n")
  expect(output).toContain("image: nginx:alpine")
  expect(output).toContain("git: r")
  expect(output).toContain("dockerfile_template: tpl")
})

test("settings show hits /api/settings/ai-prefill", async () => {
  expect(await settingsCommand(["show"])).toBe(0)
  expect(calls[0].url).toContain("/api/settings/ai-prefill")
})
test("github status hits /api/auth/github/status", async () => {
  expect(await githubCommand(["status"])).toBe(0)
  expect(calls[0].url).toContain("/api/auth/github/status")
})
