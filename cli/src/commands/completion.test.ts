import { expect, test } from "bun:test"
import { completionCommand } from "./completion"

test("each supported shell script contains every command", async () => {
  for (const shell of ["bash", "zsh", "fish", "powershell"]) {
    const lines: string[] = []
    const log = console.log; console.log = (value: string) => lines.push(value)
    try { expect(await completionCommand([shell])).toBe(0) } finally { console.log = log }
    const script = lines.join("\n")
    for (const command of ["run", "ps", "deploys", "stack", "projects", "metrics", "config"]) {
      expect(script).toContain(command)
    }
  }
})

test("unsupported shell is a usage error", async () => {
  await expect(completionCommand(["tcsh"])).rejects.toThrow()
})
