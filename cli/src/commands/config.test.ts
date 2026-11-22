import { describe, expect, test, beforeEach, afterEach } from "bun:test"
import { mkdtempSync, rmSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { configCommand } from "./config"

let directory: string
let configFile: string
const savedEnv = process.env.VELA_CONFIG
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), "vela-config-"))
  configFile = join(directory, "config.json")
  process.env.VELA_CONFIG = configFile
})
afterEach(() => {
  if (savedEnv === undefined) delete process.env.VELA_CONFIG; else process.env.VELA_CONFIG = savedEnv
  rmSync(directory, { recursive: true, force: true })
})

test("config use switches the active profile", async () => {
  const { writeStoredConfig } = await import("../config")
  writeStoredConfig({ profiles: {
    default: { server: "http://d:8000", token: "t1" },
    school: { server: "http://s:8000", token: "t2" },
  }, active: "default" })
  const output: string[] = []
  const log = console.log; console.log = (value: string) => output.push(value)
  try { expect(await configCommand(["use", "school"])).toBe(0) } finally { console.log = log }
  expect(JSON.parse(readFileSync(configFile, "utf8")).active).toBe("school")
  expect(output.join(" ")).toContain("school")
})

test("config get never prints the token", async () => {
  const { writeStoredConfig } = await import("../config")
  writeStoredConfig({ profiles: { default: { server: "http://d:8000", token: "super-secret" } }, active: "default" })
  const output: string[] = []
  const log = console.log; console.log = (value: string) => output.push(value)
  try { expect(await configCommand(["get", "token"])).toBe(0) } finally { console.log = log }
  expect(output.join(" ")).not.toContain("super-secret")
  expect(output.join(" ")).toContain("<set>")
})

test("config set creates a profile and config list names it", async () => {
  expect(await configCommand(["set", "server", "http://new:8000", "--profile", "lab"])).toBe(0)
  expect(await configCommand(["list"])).toBe(0)
  const stored = JSON.parse(readFileSync(configFile, "utf8"))
  expect(stored.profiles.lab.server).toBe("http://new:8000")
})

describe("config profile resolution", () => {
  test("config get rejects a __proto__ profile name", async () => {
    const { writeStoredConfig } = await import("../config")
    writeStoredConfig({ profiles: { default: { server: "http://d:8000", token: "t" } }, active: "default" })
    await expect(configCommand(["get", "server", "--profile", "__proto__"])).rejects.toThrow(/Unknown profile/)
  })

  test("config get honors VELA_PROFILE published by the global --profile flag", async () => {
    const { writeStoredConfig } = await import("../config")
    writeStoredConfig({ profiles: {
      default: { server: "http://DEFAULT:8000", token: "t" },
      lab: { server: "http://LAB:8000", token: "t" },
    }, active: "default" })
    const savedProfile = process.env.VELA_PROFILE
    process.env.VELA_PROFILE = "lab"
    const output: string[] = []
    const log = console.log; console.log = (value: string) => output.push(value)
    try { expect(await configCommand(["get", "server"])).toBe(0) } finally {
      console.log = log
      if (savedProfile === undefined) delete process.env.VELA_PROFILE; else process.env.VELA_PROFILE = savedProfile
    }
    expect(output.join(" ")).toContain("http://LAB:8000")
  })
})
