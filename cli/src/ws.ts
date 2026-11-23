import { request } from "./client"
import { emit } from "./output"

export function websocketUrl(
  server: string,
  path: string,
  ticket: string,
  params: Record<string, string> = {},
): string {
  const url = new URL(`${server}/api${path}`)
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  url.searchParams.set("ticket", ticket)
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value)
  }
  return url.toString()
}

export async function mintWsTicket(
  config: { server: string; token: string },
  containerId: string,
  purpose: "logs" | "exec",
): Promise<string> {
  const { ticket } = await request<{ ticket: string }>(
    config,
    "POST",
    `/containers/${containerId}/ws-ticket?purpose=${purpose}`,
  )
  return ticket
}

export interface LogStreamOptions {
  tail: number
  follow: boolean
}

export async function streamLogs(
  config: { server: string; token: string },
  containerId: string,
  options: LogStreamOptions,
): Promise<void> {
  const ticket = await mintWsTicket(config, containerId, "logs")
  const url = websocketUrl(
    config.server,
    `/containers/${containerId}/logs/stream`,
    ticket,
    { tail: String(options.tail), follow: options.follow ? "true" : "false" },
  )

  await new Promise<void>((resolve, reject) => {
    const socket = new WebSocket(url)
    socket.binaryType = "arraybuffer"
    socket.onmessage = (event) => {
      if (process.env.VELA_OUTPUT_QUIET === "1") return
      const chunk = typeof event.data === "string"
        ? event.data
        : Buffer.from(event.data).toString("utf8")
      if (process.env.VELA_OUTPUT_JSON === "1") {
        emit(chunk, () => chunk)
        return
      }
      process.stdout.write(chunk)
    }
    socket.onclose = (event?: { code?: number }) => {
      const code = event?.code
      if (code !== undefined && code !== 1000 && code !== 1001 && code !== 1005) {
        reject(new Error(`Log stream closed (code ${code}).`))
        return
      }
      resolve()
    }
    socket.onerror = () => reject(new Error("Log stream failed."))
  })
}
