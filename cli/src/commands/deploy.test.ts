import { describe, expect, test } from "bun:test"

import { parseEnv, waitForJob } from "./deploy"
import type { DeployJob } from "../types"

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
})
