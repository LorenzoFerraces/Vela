import { afterEach, beforeEach, describe, expect, test } from "bun:test"

import { parseEnv, run, waitForJob } from "./deploy"
import type { DeployJob } from "../types"

const savedEnv = { ...process.env }
const originalFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = originalFetch
  process.env = { ...savedEnv }
})

function capture(): { stdout: string[]; stderr: string[]; restore: () => void } {
  const stdout: string[] = []
  const stderr: string[] = []
  const log = console.log
  const error = console.error
  console.log = (value: string) => stdout.push(value)
  console.error = (value: string) => stderr.push(value)
  return { stdout, stderr, restore: () => { console.log = log; console.error = error } }
}

function clearOutputModes(): void {
  delete process.env.VELA_OUTPUT_JSON
  delete process.env.VELA_OUTPUT_QUIET
}

describe("parseEnv", () => {
  test("splits on the first equals sign and rejects malformed values", () => {
    expect(parseEnv(["A=B=C", "EMPTY="])).toEqual({ A: "B=C", EMPTY: "" })
    expect(() => parseEnv(["NO_EQUALS"])).toThrow()
    expect(() => parseEnv(["=VALUE"])).toThrow()
  })
})

describe("waitForJob", () => {
  test("returns a succeeded job", async () => {
    const job = { job_id: "j1", status: "succeeded", phase: "done" } as DeployJob
    const config = { server: "http://127.0.0.1:1", token: "t" }
    const result = await waitForJob(config, "j1", {
      maxAttempts: 1,
      poll: async () => [job],
    })
    expect(result).toEqual(job)
  })

  test("gives up after the bounded number of polls", async () => {
    const pending = { job_id: "j1", status: "in_progress", phase: "queued" } as DeployJob
    await expect(
      waitForJob(
        { server: "http://127.0.0.1:1", token: "t" },
        "j1",
        { maxAttempts: 2, poll: async () => [pending] },
      ),
    ).rejects.toThrow(/timed out|did not complete/i)
  })

  test("json progress goes to stderr, leaving stdout for the job", async () => {
    clearOutputModes()
    process.env.VELA_OUTPUT_JSON = "1"
    const job = { job_id: "j1", status: "succeeded", phase: "done" } as DeployJob
    const captured = capture()
    try {
      expect(await waitForJob({ server: "http://127.0.0.1:1", token: "t" }, "j1", {
        maxAttempts: 1, poll: async () => [job],
      })).toEqual(job)
    } finally { captured.restore() }
    expect(captured.stdout).toEqual([])
    expect(captured.stderr).toEqual(["[done]"])
  })

  test("ordinary progress stays on stdout", async () => {
    clearOutputModes()
    const job = { job_id: "j1", status: "succeeded", phase: "done" } as DeployJob
    const captured = capture()
    try {
      await waitForJob({ server: "http://127.0.0.1:1", token: "t" }, "j1", {
        maxAttempts: 1, poll: async () => [job],
      })
    } finally { captured.restore() }
    expect(captured.stdout).toEqual(["[done]"])
    expect(captured.stderr).toEqual([])
  })
})

describe("run --no-wait output modes", () => {
  beforeEach(() => {
    process.env.VELA_CONFIG = ""
    process.env.VELA_TOKEN = "pat_test"
    clearOutputModes()
    globalThis.fetch = (async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(
      JSON.stringify({ job_id: "j1", status: "in_progress" }),
      { status: 200, headers: { "content-type": "application/json" } },
    )) as typeof fetch
  })

  test("ordinary mode prints the queued notice and the job id", async () => {
    const captured = capture()
    try { expect(await run(["nginx", "--no-wait"])).toBe(0) } finally { captured.restore() }
    expect(captured.stdout).toEqual(["Queued deploy j1.", "j1"])
  })

  test("quiet suppresses both lines", async () => {
    process.env.VELA_OUTPUT_QUIET = "1"
    const captured = capture()
    try { expect(await run(["nginx", "--no-wait"])).toBe(0) } finally { captured.restore() }
    expect(captured.stdout).toEqual([])
  })

  test("json emits the accepted object for the job id", async () => {
    process.env.VELA_OUTPUT_JSON = "1"
    const captured = capture()
    try { expect(await run(["nginx", "--no-wait"])).toBe(0) } finally { captured.restore() }
    const emitted = captured.stdout.map((line) => JSON.parse(line))
    expect(emitted[emitted.length - 1]).toEqual({ job_id: "j1", status: "in_progress" })
  })
})
