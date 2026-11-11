import { parseArgs } from "node:util"

import { requireToken } from "../client"
import { resolveConfig } from "../config"
import { resolveContainerFromApi } from "../resolve"
import { websocketUrl } from "../ws"

interface RawStdin {
  setRawMode?: (mode: boolean) => void
  isRaw?: boolean
  on: (event: "data", listener: (chunk: Buffer) => void) => void
  off: (event: "data", listener: (chunk: Buffer) => void) => void
  resume: () => void
  pause: () => void
}

export async function exec(argv: string[]): Promise<number> {
  const separator = argv.indexOf("--")
  const command = separator >= 0 ? argv.slice(separator + 1) : []
  const head = separator >= 0 ? argv.slice(0, separator) : argv
  const { positionals } = parseArgs({
    args: head,
    options: {},
    allowPositionals: true,
  })
  const query = positionals[0]
  if (!query) {
    console.error("Usage: vela exec <name> [-- cmd...]")
    return 2
  }
  if (!process.stdin.isTTY && command.length === 0) {
    console.error(
      "Interactive exec needs a terminal. Pass a command: vela exec <name> -- <cmd>",
    )
    return 2
  }

  const config = requireToken(resolveConfig({}))
  const container = await resolveContainerFromApi(config, query)

  const { url, headers } = websocketUrl(
    config.server,
    `/containers/${container.id}/exec/ws`,
    config.token,
  )
  const stdin = process.stdin as unknown as RawStdin
  const wasRaw = stdin.isRaw ?? false

  return await new Promise<number>((resolve, reject) => {
    const socket = new WebSocket(url, { headers } as never)
    socket.binaryType = "arraybuffer"

    const restore = () => {
      stdin.off("data", onStdin)
      process.stdout.off("resize", onResize)
      stdin.setRawMode?.(wasRaw)
      stdin.pause()
    }

    const onStdin = (chunk: Buffer) => {
      if (chunk.includes(3)) {
        socket.close()
        return
      }
      socket.send(chunk.toString("utf8"))
    }

    const onResize = () => {
      socket.send(
        JSON.stringify({
          resize: { cols: process.stdout.columns ?? 80, rows: process.stdout.rows ?? 24 },
        }),
      )
    }

    socket.onopen = () => {
      stdin.setRawMode?.(true)
      stdin.resume()
      stdin.on("data", onStdin)
      process.stdout.on("resize", onResize)
      // First frame is the init shape {"cols","rows"}: the server consumes it
      // to size the exec session and does not forward it to the shell, unlike
      // the later {"resize":...} frames.
      socket.send(
        JSON.stringify({
          cols: process.stdout.columns ?? 80,
          rows: process.stdout.rows ?? 24,
        }),
      )
      if (command.length > 0) {
        // The exec endpoint always starts a shell; commands are typed into it.
        // `; exit` closes the shell (and the socket) once the command finishes.
        const line = command
          .map((part) => (/\s/.test(part) ? JSON.stringify(part) : part))
          .join(" ")
        socket.send(`${line}; exit\n`)
      }
    }

    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        process.stderr.write(`${event.data}\n`)
      } else {
        process.stdout.write(Buffer.from(event.data))
      }
    }

    socket.onclose = () => {
      restore()
      resolve(0)
    }

    socket.onerror = () => {
      restore()
      reject(new Error("Exec connection failed."))
    }
  })
}
