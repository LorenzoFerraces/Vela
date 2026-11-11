import { expect, test } from "bun:test"

import { VelaError, exitCodeFor, isVelaError, requireToken, toVelaError } from "./client"

test("API detail and code are preserved", () => {
  const error = toVelaError(403, { detail: "Account deactivated.", code: "account_deactivated" }, "fallback")
  expect(error.message).toBe("Account deactivated.")
  expect(error.code).toBe("account_deactivated")
  expect(isVelaError(error)).toBe(true)
})

test("non-JSON bodies fall back to the supplied message", () => {
  expect(toVelaError(500, null, "Server exploded.").message).toBe("Server exploded.")
})

test("exit codes map by meaning", () => {
  expect(exitCodeFor(new VelaError(401, "x"))).toBe(3)
  expect(exitCodeFor(new VelaError(403, "x"))).toBe(3)
  expect(exitCodeFor(new VelaError(404, "x"))).toBe(4)
  expect(exitCodeFor(new VelaError(422, "x"))).toBe(2)
  expect(exitCodeFor(new VelaError(500, "x"))).toBe(1)
  expect(exitCodeFor(new VelaError(0, "x"))).toBe(1)
})

test("requireToken rejects missing credentials", () => {
  expect(() => requireToken({ server: "http://host" })).toThrow(/vela login/)
})
