import { createInterface } from "node:readline/promises"

export async function promptLine(label: string): Promise<string> {
  const readline = createInterface({ input: process.stdin, output: process.stdout })
  try {
    return (await readline.question(label)).trim()
  } finally {
    readline.close()
  }
}

interface RawStdin {
  setRawMode?: (mode: boolean) => void
  isRaw?: boolean
  on: (event: "data", listener: (chunk: Buffer) => void) => void
  off: (event: "data", listener: (chunk: Buffer) => void) => void
  resume: () => void
  pause: () => void
}

export async function promptHidden(label: string): Promise<string> {
  process.stdout.write(label)
  const stdin = process.stdin as unknown as RawStdin
  const wasRaw = stdin.isRaw ?? false
  stdin.setRawMode?.(true)
  stdin.resume()

  return await new Promise<string>((resolve) => {
    const characters: string[] = []
    const cleanup = () => {
      stdin.off("data", onData)
      stdin.setRawMode?.(wasRaw)
      stdin.pause()
    }
    const onData = (chunk: Buffer) => {
      for (const character of chunk.toString("utf8")) {
        if (character === "\r" || character === "\n") {
          cleanup()
          process.stdout.write("\n")
          resolve(characters.join(""))
          return
        }
        if (character === "\u0003") {
          cleanup()
          process.stdout.write("\n")
          process.exit(130)
        }
        if (character === "\u007f" || character === "\b") {
          characters.pop()
          continue
        }
        characters.push(character)
      }
    }
    stdin.on("data", onData)
  })
}
