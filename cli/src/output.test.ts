import { expect, test } from "bun:test"
import { emit } from "./output"

test("emit prints JSON when VELA_OUTPUT_JSON is set", () => {
  const saved = process.env.VELA_OUTPUT_JSON
  process.env.VELA_OUTPUT_JSON = "1"
  const lines: string[] = []
  const log = console.log; console.log = (value: string) => lines.push(value)
  try { emit({ a: 1 }, () => "human") } finally {
    console.log = log
    if (saved === undefined) delete process.env.VELA_OUTPUT_JSON; else process.env.VELA_OUTPUT_JSON = saved
  }
  expect(lines[0]).toBe('{\n  "a": 1\n}')
})

test("emit suppresses output when quiet is set, including over json", () => {
  const savedJson = process.env.VELA_OUTPUT_JSON, savedQuiet = process.env.VELA_OUTPUT_QUIET
  process.env.VELA_OUTPUT_JSON = "1"; process.env.VELA_OUTPUT_QUIET = "1"
  const lines: string[] = []
  const log = console.log; console.log = (value: string) => lines.push(value)
  try { emit({ a: 1 }, () => "human") } finally {
    console.log = log
    if (savedJson === undefined) delete process.env.VELA_OUTPUT_JSON; else process.env.VELA_OUTPUT_JSON = savedJson
    if (savedQuiet === undefined) delete process.env.VELA_OUTPUT_QUIET; else process.env.VELA_OUTPUT_QUIET = savedQuiet
  }
  expect(lines).toEqual([])
})
