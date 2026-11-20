import { afterEach, beforeEach, expect, test } from "bun:test"

import { mintWsTicket, streamLogs } from "./ws"

const config = { server: "http://127.0.0.1:8000", token: "pat-token" }
const captured = { fetchUrls: [] as string[], fetchInit: [] as RequestInit[], wsUrls: [] as string[] }
let originalFetch: typeof fetch
let originalWebSocket: typeof WebSocket

beforeEach(() => {
  captured.fetchUrls = []
  captured.fetchInit = []
  captured.wsUrls = []
  originalFetch = globalThis.fetch
  originalWebSocket = globalThis.WebSocket

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    captured.fetchUrls.push(String(input))
    captured.fetchInit.push(init ?? {})
    return new Response(JSON.stringify({ ticket: "tkt-123" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })
  }) as typeof fetch

  class FakeWebSocket {
    binaryType = "blob"
    onmessage: ((event: { data: unknown }) => void) | null = null
    onclose: (() => void) | null = null
    onerror: (() => void) | null = null

    constructor(url: string) {
      captured.wsUrls.push(url)
      queueMicrotask(() => this.onclose?.())
    }
    send() {}
    close() {}
  }
  globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket
})

afterEach(() => {
  globalThis.fetch = originalFetch
  globalThis.WebSocket = originalWebSocket
})

test("WS streaming mints a single-use ticket and never sends access_token", async () => {
  await streamLogs(config, "container-1", { tail: 20, follow: true })

  expect(captured.fetchUrls).toEqual([
    "http://127.0.0.1:8000/api/containers/container-1/ws-ticket?purpose=logs",
  ])
  expect(captured.fetchInit[0]?.method).toBe("POST")
  expect((captured.fetchInit[0]?.headers as Record<string, string>).Authorization).toBe(
    "Bearer pat-token",
  )

  const wsUrl = new URL(captured.wsUrls[0] ?? "")
  expect(wsUrl.pathname).toBe("/api/containers/container-1/logs/stream")
  expect(wsUrl.protocol).toBe("ws:")
  expect(wsUrl.searchParams.get("ticket")).toBe("tkt-123")
  expect(wsUrl.searchParams.get("access_token")).toBeNull()
  expect(wsUrl.searchParams.get("tail")).toBe("20")
  expect(wsUrl.searchParams.get("follow")).toBe("true")

  expect(await mintWsTicket(config, "container-1", "exec")).toBe("tkt-123")
  expect(captured.fetchUrls[1]).toContain("purpose=exec")
})
