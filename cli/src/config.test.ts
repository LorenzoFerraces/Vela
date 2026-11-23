import { expect, test, beforeEach, afterEach } from "bun:test"
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  DEFAULT_SERVER,
  clearStoredConfig,
  configPath,
  readStoredConfig,
  resolveConfig,
  writeStoredConfig,
  type StoredConfig,
} from "./config"

let directory = ""
let configFile = ""

beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), "vela-config-"))
  configFile = join(directory, "config.json")
})

afterEach(() => {
  rmSync(directory, { recursive: true, force: true })
})

test("VELA_CONFIG overrides the default path", () => {
  const path = join(directory, "custom.json")
  expect(configPath({ VELA_CONFIG: path })).toBe(path)
})

test("precedence is flags > env > file > default", () => {
  const stored: StoredConfig = {
    profiles: { default: { server: "http://file", token: "file-token", tokenId: "file-id" } },
    active: "default",
  }
  expect(
    resolveConfig({ server: "http://flag", token: "flag-token" }, {}, stored),
  ).toEqual({ server: "http://flag", token: "flag-token", tokenId: undefined, profile: "default" })
  expect(
    resolveConfig({}, { VELA_API_URL: "http://env", VELA_TOKEN: "env-token" }, stored),
  ).toEqual({ server: "http://env", token: "env-token", tokenId: undefined, profile: "default" })
  expect(resolveConfig({}, {}, stored)).toEqual({
    server: "http://file", token: "file-token", tokenId: "file-id", profile: "default",
  })
  expect(resolveConfig({}, {}, null)).toEqual({
    server: DEFAULT_SERVER,
    token: undefined,
    tokenId: undefined,
    profile: "default",
  })
})

test("trailing slashes are trimmed from the server", () => {
  expect(resolveConfig({ server: "http://host:8000///" }, {}, null).server).toBe(
    "http://host:8000",
  )
})

test("stored config round-trips and is owner-readable only on POSIX", () => {
  const path = join(directory, "nested", "config.json")
  const config: StoredConfig = {
    profiles: { default: { server: "http://host", token: "secret", tokenId: "id" } },
    active: "default",
  }
  writeStoredConfig(config, path)
  expect(readStoredConfig(path)).toEqual(config)
  if (process.platform !== "win32") {
    expect(statSync(path).mode & 0o777).toBe(0o600)
  }
  expect(readFileSync(path, "utf8")).toContain('"token": "secret"')
})

test("a corrupt file reads as absent instead of throwing", () => {
  const path = join(directory, "broken.json")
  writeFileSync(path, "{not json", "utf8")
  expect(readStoredConfig(path)).toBeNull()
  expect(resolveConfig({}, {}, readStoredConfig(path)).server).toBe(DEFAULT_SERVER)
})

test("clear removes the file", () => {
  writeStoredConfig(
    { profiles: { default: { server: "http://host", token: "secret" } }, active: "default" },
    configFile,
  )
  clearStoredConfig(configFile)
  expect(readStoredConfig(configFile)).toBeNull()
})

test("migrates a legacy flat config into the default profile once", () => {
  writeFileSync(configFile, JSON.stringify({ server: "http://old:8000", token: "pat_old", tokenId: "tid_1" }))
  const stored = readStoredConfig(configFile)
  expect(stored).toEqual({ profiles: { default: { server: "http://old:8000", token: "pat_old", tokenId: "tid_1" } }, active: "default" })
  expect(JSON.parse(readFileSync(configFile, "utf8")).profiles.default.token).toBe("pat_old")
})

test("VELA_PROFILE selects a named profile and env overrides still win", () => {
  writeStoredConfig({ profiles: {
    default: { server: "http://default:8000", token: "pat_default" },
    school: { server: "http://school:8000/", token: "pat_school", tokenId: "tid_school" },
  }, active: "default" }, configFile)
  const resolved = resolveConfig({}, { VELA_PROFILE: "school", VELA_API_URL: "http://override:9000" }, readStoredConfig(configFile)!)
  expect(resolved).toEqual({ server: "http://override:9000", token: "pat_school", tokenId: "tid_school", profile: "school" })
})

test("flags.profile overrides the active profile and keeps its tokenId", () => {
  writeStoredConfig({ profiles: {
    default: { server: "http://default:8000", token: "pat_default" },
    school: { server: "http://school:8000", token: "pat_school", tokenId: "tid_school" },
  }, active: "default" }, configFile)
  expect(resolveConfig({ profile: "school" }, {}, readStoredConfig(configFile)!))
    .toEqual({ server: "http://school:8000", token: "pat_school", tokenId: "tid_school", profile: "school" })
})

test("an explicit unknown profile is a usage error before any request", () => {
  writeStoredConfig({ profiles: { default: { server: "http://d:8000", token: "t" } }, active: "default" }, configFile)
  const stored = readStoredConfig(configFile)!
  expect(() => resolveConfig({ profile: "missing" }, {}, stored)).toThrow(/Unknown profile: missing/)
  expect(() => resolveConfig({}, { VELA_PROFILE: "missing" }, stored)).toThrow(/Unknown profile: missing/)
  expect(() => resolveConfig({ profile: "missing" }, {}, null)).toThrow(/Unknown profile: missing/)
  expect(resolveConfig({}, { VELA_PROFILE: "" }, stored).profile).toBe("default")
  writeFileSync(configFile, "{not json")
  expect(readStoredConfig(configFile)).toBeNull()
})
