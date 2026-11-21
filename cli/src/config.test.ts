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
} from "./config"

let directory = ""

beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), "vela-config-"))
})

afterEach(() => {
  rmSync(directory, { recursive: true, force: true })
})

test("VELA_CONFIG overrides the default path", () => {
  const path = join(directory, "custom.json")
  expect(configPath({ VELA_CONFIG: path })).toBe(path)
})

test("precedence is flags > env > file > default", () => {
  const stored = { server: "http://file", token: "file-token", tokenId: "file-id" }
  expect(
    resolveConfig({ server: "http://flag", token: "flag-token" }, {}, stored),
  ).toEqual({ server: "http://flag", token: "flag-token", tokenId: undefined })
  expect(
    resolveConfig({}, { VELA_API_URL: "http://env", VELA_TOKEN: "env-token" }, stored),
  ).toEqual({ server: "http://env", token: "env-token", tokenId: undefined })
  expect(resolveConfig({}, {}, stored)).toEqual(stored)
  expect(resolveConfig({}, {}, null)).toEqual({
    server: DEFAULT_SERVER,
    token: undefined,
    tokenId: undefined,
  })
})

test("trailing slashes are trimmed from the server", () => {
  expect(resolveConfig({ server: "http://host:8000///" }, {}, null).server).toBe(
    "http://host:8000",
  )
})

test("stored config round-trips and is owner-readable only on POSIX", () => {
  const path = join(directory, "nested", "config.json")
  writeStoredConfig({ server: "http://host", token: "secret", tokenId: "id" }, path)
  expect(readStoredConfig(path)).toEqual({
    server: "http://host",
    token: "secret",
    tokenId: "id",
  })
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
  const path = join(directory, "config.json")
  writeStoredConfig({ server: "http://host", token: "secret" }, path)
  clearStoredConfig(path)
  expect(readStoredConfig(path)).toBeNull()
})
