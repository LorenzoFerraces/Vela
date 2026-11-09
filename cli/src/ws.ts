export function websocketUrl(
  server: string,
  path: string,
  token: string,
  params: Record<string, string> = {},
): { url: string; headers: Record<string, string> } {
  const url = new URL(`${server}/api${path}`)
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value)
  }
  return { url: url.toString(), headers: { Authorization: `Bearer ${token}` } }
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
  const { url, headers } = websocketUrl(
    config.server,
    `/containers/${containerId}/logs/stream`,
    config.token,
    { tail: String(options.tail), follow: options.follow ? "true" : "false" },
  )

  await new Promise<void>((resolve, reject) => {
    const socket = new WebSocket(url, { headers } as never)
    socket.binaryType = "arraybuffer"
    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        process.stdout.write(event.data)
      } else {
        process.stdout.write(Buffer.from(event.data).toString("utf8"))
      }
    }
    socket.onclose = () => resolve()
    socket.onerror = () => reject(new Error("Log stream failed."))
  })
}
