export function websocketUrl(
  server: string,
  path: string,
  token: string,
  params: Record<string, string> = {},
): string {
  const url = new URL(`${server}/api${path}`)
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  url.searchParams.set("access_token", token)
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value)
  }
  return url.toString()
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
  const url = websocketUrl(
    config.server,
    `/containers/${containerId}/logs/stream`,
    config.token,
    { tail: String(options.tail), follow: options.follow ? "true" : "false" },
  )

  await new Promise<void>((resolve, reject) => {
    const socket = new WebSocket(url)
    socket.binaryType = "arraybuffer"
    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        process.stdout.write(event.data)
      } else {
        process.stdout.write(Buffer.from(event.data).toString("utf8"))
      }
    }
    socket.onclose = (event) => {
      if (event.code !== 1000 && event.code !== 1001 && event.code !== 1005) {
        reject(new Error(`Log stream closed (code ${event.code}).`))
        return
      }
      resolve()
    }
    socket.onerror = () => reject(new Error("Log stream failed."))
  })
}
